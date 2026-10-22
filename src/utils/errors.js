// Backend error helpers.

/** Flatten a FastAPI / Pydantic error body into one readable string. */
export async function readErrorDetail(res) {
  let detail = res.statusText || `HTTP ${res.status}`;
  try {
    const body = await res.json();
    const d = body.detail;
    if (Array.isArray(d)) {
      detail = d.map((e) => {
        const loc = (e.loc || []).slice(1).join(' → ');
        return loc ? `${loc}: ${e.msg}` : (e.msg || String(e));
      }).join('; ');
    } else if (typeof d === 'string') detail = d;
    else if (d != null) detail = JSON.stringify(d);
  } catch { /* not JSON */ }
  return detail;
}

export function isNetworkError(err) {
  return err instanceof TypeError && /fetch|network|failed/i.test(err.message);
}

/** Map a load failure to an i18n key (or null for a generic message). */
export function loadErrorKey(detail) {
  if (/unsupported audio format/i.test(detail)) return 'toast.unsupported_format';
  if (/file too large/i.test(detail)) return 'toast.file_too_large';
  if (/failed to (read|decode)/i.test(detail)) return 'toast.decode_failed';
  if (/out of memory/i.test(detail)) return 'toast.out_of_memory';
  return null;
}

/** Map an export failure to an i18n key (or null). */
export function exportErrorKey(detail) {
  if (/permission denied|access is denied|cannot write/i.test(detail)) return 'toast.export_permission';
  if (/no space left|disk full|not enough space/i.test(detail)) return 'toast.export_disk_full';
  if (/path too long/i.test(detail)) return 'toast.export_path_too_long';
  return null;
}
