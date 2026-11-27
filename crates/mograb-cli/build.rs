// SPDX-License-Identifier: GPL-3.0-only
fn main() {
    #[cfg(target_os = "windows")]
    {
        let mut res = winres::WindowsResource::new();
        res.set_icon("../../assets/icon.ico");
        res.compile().expect("embed Windows icon");
    }
}
