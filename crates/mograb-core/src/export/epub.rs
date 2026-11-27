// SPDX-License-Identifier: GPL-3.0-only
//! EPUB 3 导出器（零 AGPL 依赖，自研 ZIP + XHTML + OPF + NCX）。

use super::base::{ExportResult, Exporter, book_variables, render_template};
use crate::content::normalizer::split_paragraphs;
use crate::domain::book::Book;
use crate::domain::chapter::Chapter;
use crate::domain::enums::ExportFormat;
use crate::errors::{MoGrabError, MoGrabResult};
use async_trait::async_trait;
use chrono::{DateTime, Utc};
use serde_json::json;
use std::collections::BTreeMap;
use std::fs::{self, File};
use std::io::Write;
use std::path::{Path, PathBuf};
use tracing::{info, warn};
use uuid::Uuid;
use zip::CompressionMethod;
use zip::write::{SimpleFileOptions, ZipWriter};

pub const MIMETYPE: &str = "application/epub+zip";
pub const DEFAULT_LANGUAGE: &str = "zh-CN";
pub const DEFAULT_CSS: &str = r#"body { font-family: serif; line-height: 1.6; margin: 1em; }
h1 { font-size: 1.4em; margin: 1.2em 0 0.8em; }
p { text-indent: 2em; margin: 0.5em 0; }
.cover { text-align: center; }
"#;

const CONTAINER_XML: &str = r#"<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"#;

fn escape_xml(s: &str) -> String {
    html_escape::encode_text(s).into_owned()
}

fn image_media_type(ext: &str) -> Option<&'static str> {
    match ext.to_lowercase().as_str() {
        ".jpg" | ".jpeg" | "jpg" | "jpeg" => Some("image/jpeg"),
        ".png" | "png" => Some("image/png"),
        ".gif" | "gif" => Some("image/gif"),
        ".webp" | "webp" => Some("image/webp"),
        _ => None,
    }
}

fn isoformat(dt: DateTime<Utc>) -> String {
    dt.format("%Y-%m-%dT%H:%M:%SZ").to_string()
}

#[derive(Debug, Clone)]
pub struct EpubExporter {
    css: String,
    include_cover: bool,
    covers_dir: Option<PathBuf>,
    metadata_templates: BTreeMap<String, String>,
}

impl Default for EpubExporter {
    fn default() -> Self {
        Self {
            css: DEFAULT_CSS.to_string(),
            include_cover: true,
            covers_dir: None,
            metadata_templates: BTreeMap::new(),
        }
    }
}

impl EpubExporter {
    pub fn new(
        css: Option<String>,
        include_cover: bool,
        covers_dir: Option<PathBuf>,
        metadata_templates: BTreeMap<String, String>,
    ) -> Self {
        Self {
            css: css.unwrap_or_else(|| DEFAULT_CSS.to_string()),
            include_cover,
            covers_dir,
            metadata_templates,
        }
    }

    fn write_epub_sync(
        &self,
        book: &Book,
        chapters: &[Chapter],
        target: &Path,
    ) -> std::io::Result<u64> {
        if let Some(parent) = target.parent() {
            fs::create_dir_all(parent)?;
        }
        let file = File::create(target)?;
        let mut zip = ZipWriter::new(file);

        let stored = SimpleFileOptions::default().compression_method(CompressionMethod::Stored);
        let deflated = SimpleFileOptions::default().compression_method(CompressionMethod::Deflated);

        let urn_input = format!("mograb:{}", book.id);
        let book_uuid = Uuid::new_v5(&Uuid::NAMESPACE_URL, urn_input.as_bytes());
        let book_id = format!("urn:uuid:{book_uuid}");

        // 1) mimetype 必须第一个写入且不压缩
        zip.start_file("mimetype", stored)?;
        zip.write_all(MIMETYPE.as_bytes())?;

        // 2) container.xml
        zip.start_file("META-INF/container.xml", deflated)?;
        zip.write_all(CONTAINER_XML.as_bytes())?;

        // 3) 样式
        zip.start_file("OEBPS/style.css", deflated)?;
        zip.write_all(self.css.as_bytes())?;

        // 4) 章节
        let mut manifest_items = Vec::new();
        let mut spine_items = Vec::new();
        let mut nav_points = Vec::new();

        for (idx, chapter) in chapters.iter().enumerate() {
            let i = idx + 1;
            let name = format!("chapter_{i:04}.xhtml");
            let xhtml = Self::render_chapter_xhtml(chapter);
            zip.start_file(format!("OEBPS/{name}"), deflated)?;
            zip.write_all(xhtml.as_bytes())?;

            manifest_items.push(format!(
                r#"    <item id="ch{i}" href="{name}" media-type="application/xhtml+xml"/>"#
            ));
            spine_items.push(format!(r#"    <itemref idref="ch{i}"/>"#));
            nav_points.push(format!(
                r#"      <li><a href="{name}">{}</a></li>"#,
                escape_xml(&chapter.title)
            ));
        }

        // 5) 导航文档
        let nav_xhtml = Self::render_nav(book, &nav_points);
        zip.start_file("OEBPS/toc.xhtml", deflated)?;
        zip.write_all(nav_xhtml.as_bytes())?;
        manifest_items.push(
            r#"    <item id="toc" href="toc.xhtml" media-type="application/xhtml+xml" properties="nav"/>"#
                .to_string(),
        );

        // 6) NCX
        let ncx = Self::render_ncx(book, chapters, &book_id);
        zip.start_file("OEBPS/toc.ncx", deflated)?;
        zip.write_all(ncx.as_bytes())?;
        manifest_items.push(
            r#"    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>"#
                .to_string(),
        );
        manifest_items
            .push(r#"    <item id="css" href="style.css" media-type="text/css"/>"#.to_string());

        // 7) 封面
        let cover = self.load_cover(book);
        let has_cover = cover.is_some();
        if let Some((image_name, media_type, image_bytes)) = cover {
            zip.start_file(format!("OEBPS/{image_name}"), deflated)?;
            zip.write_all(&image_bytes)?;
            let cover_xhtml = Self::render_cover_xhtml(book, &image_name);
            zip.start_file("OEBPS/cover.xhtml", deflated)?;
            zip.write_all(cover_xhtml.as_bytes())?;

            manifest_items.insert(
                0,
                format!(
                    r#"    <item id="cover-image" href="{image_name}" media-type="{media_type}" properties="cover-image"/>"#
                ),
            );
            manifest_items.insert(
                1,
                r#"    <item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>"#
                    .to_string(),
            );
            spine_items.insert(0, r#"    <itemref idref="cover"/>"#.to_string());
        }

        // 8) OPF
        let opf = self.render_opf(book, &book_id, &manifest_items, &spine_items, has_cover);
        zip.start_file("OEBPS/content.opf", deflated)?;
        zip.write_all(opf.as_bytes())?;

        zip.finish()?;
        Ok(fs::metadata(target)?.len())
    }

    fn load_cover(&self, book: &Book) -> Option<(String, String, Vec<u8>)> {
        if !self.include_cover {
            return None;
        }
        let covers_dir = self.covers_dir.as_ref()?;
        let cover_rel = book.cover_path.as_deref()?;
        if cover_rel.is_empty() {
            return None;
        }
        let file_name = Path::new(cover_rel).file_name()?;
        let path = covers_dir.join(file_name);
        if !path.is_file() {
            warn!(book_id = %book.id, path = %path.display(), "export.cover_missing");
            return None;
        }
        let ext = path
            .extension()
            .and_then(|s| s.to_str())
            .map(|s| s.to_lowercase())?;
        let Some(mt) = image_media_type(&ext) else {
            warn!(book_id = %book.id, suffix = %ext, "export.cover_unknown_type");
            return None;
        };
        let bytes = fs::read(&path).ok()?;
        Some((format!("cover.{ext}"), mt.to_string(), bytes))
    }

    fn render_chapter_xhtml(chapter: &Chapter) -> String {
        let paragraphs = split_paragraphs(chapter.content.as_deref().unwrap_or(""));
        let body = if paragraphs.is_empty() {
            "    <p><em>（本章内容为空）</em></p>".to_string()
        } else {
            paragraphs
                .into_iter()
                .map(|p| format!("    <p>{}</p>", escape_xml(&p)))
                .collect::<Vec<_>>()
                .join("\n")
        };
        let title = escape_xml(&chapter.title);
        format!(
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n\
<!DOCTYPE html>\n\
<html xmlns=\"http://www.w3.org/1999/xhtml\" xmlns:epub=\"http://www.idpf.org/2007/ops\" xml:lang=\"zh-CN\">\n\
<head>\n\
  <title>{title}</title>\n\
  <link rel=\"stylesheet\" type=\"text/css\" href=\"style.css\"/>\n\
</head>\n\
<body>\n\
  <h1>{title}</h1>\n\
{body}\n\
</body>\n\
</html>\n"
        )
    }

    fn render_cover_xhtml(book: &Book, image_name: &str) -> String {
        let title = escape_xml(&book.title);
        format!(
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n\
<!DOCTYPE html>\n\
<html xmlns=\"http://www.w3.org/1999/xhtml\" xmlns:epub=\"http://www.idpf.org/2007/ops\" xml:lang=\"zh-CN\" lang=\"zh-CN\">\n\
  <head>\n\
    <title>{title}</title>\n\
    <link rel=\"stylesheet\" type=\"text/css\" href=\"style.css\"/>\n\
  </head>\n\
  <body class=\"cover\">\n\
    <img src=\"{image_name}\" alt=\"{title}\"/>\n\
  </body>\n\
</html>\n"
        )
    }

    fn render_nav(book: &Book, nav_points: &[String]) -> String {
        let items = if nav_points.is_empty() {
            "      <li><span>（无章节）</span></li>".to_string()
        } else {
            nav_points.join("\n")
        };
        let title = escape_xml(&book.title);
        format!(
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n\
<!DOCTYPE html>\n\
<html xmlns=\"http://www.w3.org/1999/xhtml\" xmlns:epub=\"http://www.idpf.org/2007/ops\" xml:lang=\"zh-CN\">\n\
<head>\n\
  <title>{title}</title>\n\
</head>\n\
<body>\n\
  <nav epub:type=\"toc\" id=\"toc\">\n\
    <h1>目录</h1>\n\
    <ol>\n\
{items}\n\
    </ol>\n\
  </nav>\n\
</body>\n\
</html>\n"
        )
    }

    fn render_ncx(book: &Book, chapters: &[Chapter], book_id: &str) -> String {
        let points = chapters
            .iter()
            .enumerate()
            .map(|(idx, c)| {
                let i = idx + 1;
                format!(
                    "    <navPoint id=\"nav{i}\" playOrder=\"{i}\">\n\
      <navLabel><text>{}</text></navLabel>\n\
      <content src=\"chapter_{i:04}.xhtml\"/>\n\
    </navPoint>",
                    escape_xml(&c.title)
                )
            })
            .collect::<Vec<_>>()
            .join("\n");
        let title = escape_xml(&book.title);
        format!(
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n\
<ncx xmlns=\"http://www.daisy.org/z3986/2005/ncx/\" version=\"2005-1\">\n\
  <head>\n\
    <meta name=\"dtb:uid\" content=\"{book_id}\"/>\n\
    <meta name=\"dtb:depth\" content=\"1\"/>\n\
  </head>\n\
  <docTitle><text>{title}</text></docTitle>\n\
  <navMap>\n\
{points}\n\
  </navMap>\n\
</ncx>\n"
        )
    }

    fn render_opf(
        &self,
        book: &Book,
        book_id: &str,
        manifest_items: &[String],
        spine_items: &[String],
        has_cover: bool,
    ) -> String {
        let modified = isoformat(book.updated_at);
        let created = isoformat(book.created_at);
        let manifest = manifest_items.join("\n");
        let spine = spine_items.join("\n");

        let mut fields = BTreeMap::new();
        fields.insert("title".to_string(), book.title.clone());
        fields.insert(
            "creator".to_string(),
            book.author
                .clone()
                .filter(|a| !a.is_empty())
                .unwrap_or_else(|| "Unknown".to_string()),
        );
        fields.insert(
            "language".to_string(),
            book.language
                .clone()
                .filter(|l| !l.is_empty())
                .unwrap_or_else(|| DEFAULT_LANGUAGE.to_string()),
        );
        fields.insert("source".to_string(), book.source_id.clone());

        if let Some(ref intro) = book.intro
            && !intro.is_empty()
        {
            fields.insert("description".to_string(), intro.clone());
        }
        if let Some(pub_val) = book.metadata.get("publisher").and_then(|v| v.as_str())
            && !pub_val.is_empty()
        {
            fields.insert("publisher".to_string(), pub_val.to_string());
        }

        let vars = book_variables(book);
        for (k, tpl) in &self.metadata_templates {
            let rendered = render_template(tpl, &vars);
            if !rendered.is_empty() {
                fields.insert(k.clone(), rendered);
            }
        }

        let mut head_meta = String::new();
        for key in ["title", "creator", "language"] {
            if let Some(val) = fields.get(key) {
                head_meta.push_str(&format!("    <dc:{key}>{}</dc:{key}>\n", escape_xml(val)));
            }
        }

        let mut meta_extra = String::new();
        for (key, val) in &fields {
            if matches!(key.as_str(), "title" | "creator" | "language") {
                continue;
            }
            meta_extra.push_str(&format!("    <dc:{key}>{}</dc:{key}>\n", escape_xml(val)));
        }

        let cover_meta = if has_cover {
            "    <meta name=\"cover\" content=\"cover-image\"/>\n"
        } else {
            ""
        };

        format!(
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n\
<package xmlns=\"http://www.idpf.org/2007/opf\" version=\"3.0\" unique-identifier=\"bookid\">\n\
  <metadata xmlns:dc=\"http://purl.org/dc/elements/1.1/\">\n\
    <dc:identifier id=\"bookid\">{book_id}</dc:identifier>\n\
{head_meta}{meta_extra}    <meta property=\"dcterms:modified\">{modified}</meta>\n\
    <meta property=\"dcterms:created\">{created}</meta>\n\
{cover_meta}  </metadata>\n\
  <manifest>\n\
{manifest}\n\
  </manifest>\n\
  <spine toc=\"ncx\">\n\
{spine}\n\
  </spine>\n\
</package>\n"
        )
    }
}

#[async_trait]
impl Exporter for EpubExporter {
    fn format(&self) -> ExportFormat {
        ExportFormat::Epub
    }

    async fn export(
        &self,
        book: &Book,
        chapters: &[Chapter],
        target: &Path,
    ) -> MoGrabResult<ExportResult> {
        let exporter = self.clone();
        let book_cloned = book.clone();
        let chapters_cloned = chapters.to_vec();
        let target_owned = target.to_path_buf();

        let size = tokio::task::spawn_blocking(move || {
            exporter.write_epub_sync(&book_cloned, &chapters_cloned, &target_owned)
        })
        .await
        .map_err(|e| MoGrabError::export(e.to_string(), json!({})))?
        .map_err(|e| MoGrabError::export(format!("EPUB 写入失败: {e}"), json!({})))?;

        info!(book_id = %book.id, path = %target.display(), size, "export.epub");
        Ok(ExportResult {
            book_id: book.id.clone(),
            format: ExportFormat::Epub,
            path: target.to_path_buf(),
            size_bytes: size,
            chapter_count: chapters.len(),
            warnings: Vec::new(),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::domain::enums::BookStatus;
    use serde_json::Map;
    use std::io::Read;
    use zip::ZipArchive;

    #[tokio::test]
    async fn test_epub_structure_and_mimetype_stored_first() {
        let dir = tempfile::tempdir().unwrap();
        let now = Utc::now();
        let mut meta = Map::new();
        meta.insert("publisher".into(), serde_json::json!("测试社"));

        let book = Book {
            id: "book_01J8X2QK000000000000000000".into(),
            source_id: "example".into(),
            source_book_id: "1001".into(),
            url: "https://example.com/book/1001".into(),
            title: "三体".into(),
            author: Some("刘慈欣".into()),
            intro: Some("科幻小说".into()),
            language: Some("zh-CN".into()),
            cover_url: None,
            cover_path: None,
            status: BookStatus::Completed,
            latest_chapter: Some("第一章".into()),
            word_count: 100,
            chapter_count: 1,
            created_at: now,
            updated_at: now,
            metadata: meta,
        };
        let chapters = vec![Chapter {
            id: "chap_1".into(),
            book_id: book.id.clone(),
            source_chapter_id: Some("c1".into()),
            title: "第一章 科学边界".into(),
            url: "https://example.com/1".into(),
            index: 0,
            content: Some("第一段。\n\n第二段。".into()),
            content_hash: None,
            word_count: 10,
            created_at: now,
            updated_at: now,
        }];

        let out = dir.path().join("out.epub");
        let exporter = EpubExporter::default();
        let res = exporter.export(&book, &chapters, &out).await.unwrap();
        assert!(res.size_bytes > 0);

        let file = File::open(&out).unwrap();
        let mut archive = ZipArchive::new(file).unwrap();
        {
            let mut first = archive.by_index(0).unwrap();
            assert_eq!(first.name().unwrap().as_ref(), "mimetype");
            assert_eq!(first.compression(), CompressionMethod::Stored);
            let mut mime = String::new();
            first.read_to_string(&mut mime).unwrap();
            assert_eq!(mime, MIMETYPE);
        }

        let mut opf = String::new();
        archive
            .by_name("OEBPS/content.opf")
            .unwrap()
            .read_to_string(&mut opf)
            .unwrap();
        assert!(opf.contains("<dc:title>三体</dc:title>"));
        assert!(opf.contains("dcterms:modified"));
        assert!(opf.contains("dcterms:created"));
        assert!(archive.by_name("OEBPS/toc.ncx").is_ok());
        assert!(archive.by_name("OEBPS/toc.xhtml").is_ok());
        assert!(archive.by_name("OEBPS/chapter_0001.xhtml").is_ok());
    }
}
