import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import Segmented from './controls/Segmented';
import { PlayIcon, StopIcon, UndoIcon, RedoIcon } from './Icons';
import { formatHz, formatTime } from '../utils/note_utils';

/** Transport · A/B · levels · undo/redo · export buttons. */
export default function Footer({
  player, abMode, onAB, hasProcessed, levels,
  history, audioLoaded, busy, onAction,
}) {
  const { t } = useTranslation();
  // Position text is written straight from the player's frame callback, so
  // playback does not re-render the app. Text changes cost a style + layout
  // pass, so the readout updates at most every 50 ms (the playhead itself is
  // drawn every frame); a stop or seek always lands immediately.
  const posRef = useRef(null);
  const lastWrite = useRef(0);
  const { subscribe, playing } = player;
  const playingRef = useRef(playing); playingRef.current = playing;
  useEffect(() => subscribe?.((pos) => {
    const now = performance.now();
    if (playingRef.current && pos > 0 && now - lastWrite.current < 50) return;
    lastWrite.current = now;
    const text = formatTime(pos);
    if (posRef.current && posRef.current.textContent !== text) posRef.current.textContent = text;
  }), [subscribe]);
  return (
    <div className="footer">
      <div className="transport">
        <button
          type="button" className="btn btn--play" onClick={player.toggle}
          title={`${player.playing ? t('footer.stop') : t('footer.play')} (Space)`}
          aria-label={player.playing ? t('footer.stop') : t('footer.play')}
          disabled={!audioLoaded}
        >
          {player.playing ? <StopIcon /> : <PlayIcon />}
        </button>
        <span className="transport__time" aria-live="off">
          <span ref={posRef} className="transport__pos">{formatTime(0)}</span> <span>/ {formatTime(player.duration)}</span>
        </span>
        <Segmented
          ariaLabel={t('footer.ab')} value={abMode} onChange={onAB}
          options={[
            { value: 'original',  label: t('footer.a'), title: `${t('footer.ab')} (A)` },
            { value: 'processed', label: t('footer.b'), title: `${t('footer.ab')} (A)` },
          ]}
          disabled={!hasProcessed}
        />
        <span className="levels">
          <span><b>{t('footer.peak')}</b> <i>{formatHz(levels.peak, 1)} dB</i></span>
          <span><b>{t('footer.rms')}</b> <i>{formatHz(levels.rms, 1)} dB</i></span>
        </span>
      </div>
      <span className="footer__spacer" />
      <span className="history">
        <button type="button" className="btn btn--icon" onClick={history.undo} disabled={!history.canUndo} title={`${t('footer.undo')} (Ctrl+Z)`} aria-label={t('footer.undo')}><UndoIcon /></button>
        <button type="button" className="btn btn--icon" onClick={history.redo} disabled={!history.canRedo} title={`${t('footer.redo')} (Ctrl+Shift+Z)`} aria-label={t('footer.redo')}><RedoIcon /></button>
      </span>
      <button type="button" className="btn" onClick={() => onAction('multisample')} disabled={!audioLoaded}>{t('footer.multisample')} <kbd>Ctrl+M</kbd></button>
      <button type="button" className="btn" onClick={() => onAction('quickExport')} disabled={!audioLoaded || busy}>{t('footer.quick_export')} <kbd>Ctrl+Shift+E</kbd></button>
      <button type="button" className="btn btn--primary" onClick={() => onAction('export')} disabled={!audioLoaded || busy}>{t('footer.export_wav')} <kbd>Ctrl+E</kbd></button>
    </div>
  );
}
