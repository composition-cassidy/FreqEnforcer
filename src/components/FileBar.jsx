import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import logoSrc from '../assets/LOGO.png';
import { getCssVar, onThemeChange } from '../utils/themeColors';
import './FileBar.css';

function hexToHue(hex) {
  const h = hex.replace('#', '').trim();
  const r = parseInt(h.slice(0, 2), 16) / 255;
  const g = parseInt(h.slice(2, 4), 16) / 255;
  const b = parseInt(h.slice(4, 6), 16) / 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
  if (d === 0) return 0;
  let hue;
  if (max === r)      hue = ((g - b) / d) % 6;
  else if (max === g) hue = (b - r) / d + 2;
  else                hue = (r - g) / d + 4;
  return ((hue * 60) + 360) % 360;
}

function computeLogoFilter() {
  const accentHex = getCssVar('--accent', '#33CED6');
  const delta = hexToHue(accentHex) - 210;
  return `hue-rotate(${delta.toFixed(1)}deg)`;
}

export default function FileBar({ filePath, onFileLoad, loading = false }) {
  const { t } = useTranslation();
  const [dragging, setDragging] = useState(false);
  const [logoFilter, setLogoFilter] = useState(computeLogoFilter);

  useEffect(() => {
    return onThemeChange(() => setLogoFilter(computeLogoFilter()));
  }, []);

  async function handleBrowse() {
    try {
      const path = await window.electronAPI?.openFileDialog();
      if (path) onFileLoad(path);
    } catch (e) {
      console.warn('File dialog error:', e);
    }
  }

  function handleDragEnter(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
  }

  function handleDragOver(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
    setDragging(true);
  }

  function handleDragLeave(e) {
    // Only clear if mouse truly left the bar (not just entered a child)
    if (!e.currentTarget.contains(e.relatedTarget)) setDragging(false);
  }

  function handleDrop(e) {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (!file) return;
    // File.path is stripped by contextIsolation; the preload captures it.
    const realPath = window.electronAPI?.getLastDroppedFilePath?.();
    onFileLoad(realPath || file);
  }

  return (
    <div
      className={`file-bar${dragging ? ' file-bar--drag' : ''}${loading ? ' file-bar--loading' : ''}`}
      onDragEnter={handleDragEnter}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <img className="file-bar-logo" src={logoSrc} alt="FreqEnforcer" draggable={false} style={{ filter: logoFilter }} />

      <span className="file-bar-label">{t('electron.filebar.input_label')}</span>

      <div className="file-bar-path-wrap">
        <input
          className="file-bar-path"
          readOnly
          value={filePath ?? ''}
          placeholder={t('electron.filebar.placeholder')}
          title={filePath ?? ''}
        />
      </div>

      <button
        className="file-bar-browse"
        onClick={handleBrowse}
        disabled={loading}
        type="button"
      >
        {loading ? t('electron.filebar.loading') : t('electron.filebar.browse')}
      </button>
    </div>
  );
}
