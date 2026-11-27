// SPDX-License-Identifier: GPL-3.0-only
//! 内部 ID 生成（ULID，Crockford Base32）。

use rand::Rng;
use std::time::{SystemTime, UNIX_EPOCH};

const ALPHABET: &[u8; 32] = b"0123456789ABCDEFGHJKMNPQRSTVWXYZ";
const ULID_LEN: usize = 26;

pub fn new_ulid() -> String {
    let ms = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0);
    new_ulid_with_timestamp(ms)
}

pub fn new_ulid_with_timestamp(timestamp_ms: u64) -> String {
    assert!(
        timestamp_ms < (1u64 << 48),
        "时间戳超出 48 位范围: {timestamp_ms}"
    );
    let mut rand_bytes = [0u8; 10];
    rand::rng().fill_bytes(&mut rand_bytes);

    let mut rand_hi: u16 = ((rand_bytes[0] as u16) << 8) | (rand_bytes[1] as u16);
    let _ = &mut rand_hi;
    let mut value: u128 = (timestamp_ms as u128) << 80;
    for (i, b) in rand_bytes.iter().enumerate() {
        let shift = (9 - i) * 8;
        value |= (*b as u128) << shift;
    }

    let mut out = String::with_capacity(ULID_LEN);
    for idx in (0..ULID_LEN).rev() {
        let shift = idx * 5;
        let ch = ALPHABET[((value >> shift) & 0x1F) as usize] as char;
        out.push(ch);
    }
    out
}

pub fn new_id(prefix: &str) -> String {
    format!("{prefix}_{}", new_ulid())
}

pub fn new_id_with_timestamp(prefix: &str, timestamp_ms: u64) -> String {
    format!("{prefix}_{}", new_ulid_with_timestamp(timestamp_ms))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_ulid_format_and_ordering() {
        let id1 = new_id_with_timestamp("book", 1_700_000_000_000);
        let id2 = new_id_with_timestamp("book", 1_700_000_000_100);
        assert!(id1.starts_with("book_"));
        assert_eq!(id1.len(), 5 + 26);
        assert!(id1 < id2);
        for ch in id1["book_".len()..].chars() {
            assert!(!matches!(ch, 'I' | 'L' | 'O' | 'U'));
        }
    }
}
