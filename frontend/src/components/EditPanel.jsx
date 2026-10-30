import React, { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { editImage, approveImage } from '../api/client.js'

const SUGGESTIONS = [
  {
    label: 'Remove number badge',
    prompt: 'Remove the multiplier number badge/tag (e.g. the "3" or "x3" label) from the image. Keep every product, its packaging, colours, text and logos exactly the same — change nothing else.',
  },
  { label: 'Add more space', prompt: 'Add more space between the products' },
  { label: 'Make bigger', prompt: 'Make the products slightly bigger' },
  { label: 'Center products', prompt: 'Center the products in the image' },
]

export default function EditPanel({ bundle, onClose, onUpdate }) {
  const [prompt, setPrompt] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [editedImagePath, setEditedImagePath] = useState(null)
  const [warnings, setWarnings] = useState([])
  const [editHistory, setEditHistory] = useState([])
  const [justApplied, setJustApplied] = useState(false)
  const [approving, setApproving] = useState(false)
  const [approved, setApproved] = useState(false)

  const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'
  const busy = loading || approving

  const currentImage = editedImagePath || bundle.generated_image || bundle.original_image
  // Cache-bust with the edit count so successive edits (same filename) visibly update.
  const currentImageSrc = currentImage
    ? `${API_BASE}/api/images/${currentImage.split('/').pop()}?v=${editHistory.length}`
    : null
  const originalSrc = bundle.original_image
    ? `${API_BASE}/api/images/${bundle.original_image.split('/').pop()}`
    : null

  // A real pop-up: lock the page behind it and close on Escape.
  useEffect(() => {
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    function onKey(e) {
      if (e.key === 'Escape' && !busy) onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = prevOverflow
      window.removeEventListener('keydown', onKey)
    }
  }, [busy, onClose])

  async function handleEdit(retryPrompt) {
    const thisPrompt = (typeof retryPrompt === 'string' ? retryPrompt : prompt).trim()
    if (!thisPrompt || loading) return
    setLoading(true)
    setError(null)
    setWarnings([])
    setJustApplied(false)
    try {
      // Successive edits build on the last result.
      const imagePath = editedImagePath || bundle.generated_image || bundle.original_image
      const referencePaths = (bundle.products || []).map(p => p.image_path).filter(Boolean)
      const result = await editImage(bundle.code, imagePath, thisPrompt, referencePaths)
      setEditedImagePath(result.image_path)
      if (result.warnings) setWarnings(result.warnings)
      setEditHistory(prev => [...prev, { prompt: thisPrompt, time: new Date().toLocaleTimeString() }])
      // Update the dashboard card immediately — no refresh needed.
      onUpdate({ ...bundle, generated_image: result.image_path })
      setPrompt('')
      setJustApplied(true)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleApprove() {
    if (approving) return
    setApproving(true)
    setError(null)
    try {
      const imagePath = editedImagePath || bundle.generated_image || bundle.original_image
      await approveImage(bundle.code, imagePath, bundle.title)
      setApproved(true)
      onUpdate({ ...bundle, generated_image: imagePath })
      setTimeout(onClose, 900)
    } catch (err) {
      setError(err.message)
    } finally {
      setApproving(false)
    }
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleEdit()
  }

  const lastPrompt = editHistory.length ? editHistory[editHistory.length - 1].prompt : ''

  return createPortal(
    <div
      className="edit-modal-backdrop"
      onMouseDown={e => { if (e.target === e.currentTarget && !busy) onClose() }}
    >
      <div className="edit-modal" role="dialog" aria-modal="true" aria-labelledby="edit-modal-title">
        <header className="edit-modal-header">
          <div className="edit-modal-heading">
            <span className="eyebrow">Edit image · {bundle.code}</span>
            <h2 id="edit-modal-title">{bundle.title || 'Untitled bundle'}</h2>
          </div>
          <button className="close-btn" onClick={onClose} disabled={busy} aria-label="Close editor">✕</button>
        </header>

        <div className="edit-modal-body">
          <div className="edit-compare">
            <figure className="edit-figure">
              <figcaption>Original</figcaption>
              <div className="edit-frame">
                {originalSrc
                  ? <img src={originalSrc} alt="Original bundle" />
                  : <div className="no-image">No original</div>}
              </div>
            </figure>
            <figure className="edit-figure is-current">
              <figcaption>
                {editHistory.length ? `Edited · version ${editHistory.length}` : 'Current'}
              </figcaption>
              <div className="edit-frame">
                {currentImageSrc
                  ? <img src={currentImageSrc} alt="Current bundle" />
                  : <div className="no-image">No image</div>}
                {loading && (
                  <div className="edit-loading-overlay">
                    <div className="spinner"></div>
                    <p>Applying your edit…</p>
                  </div>
                )}
              </div>
            </figure>
          </div>

          {justApplied && !loading && (
            <div className="edit-status is-success">
              ✓ Edit applied — “{lastPrompt}”. Compare it with the original, keep refining, or approve.
            </div>
          )}
          {approved && <div className="edit-status is-success">✓ Approved — added to the export.</div>}
          {warnings.length > 0 && (
            <div className="edit-status is-warning">
              <strong>Check the result:</strong>
              <ul>{warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
            </div>
          )}
          {error && (
            <div className="edit-status is-error">
              <span><strong>Edit failed:</strong> {error}</span>
              <button onClick={() => handleEdit(lastPrompt || undefined)} disabled={loading}>Retry</button>
            </div>
          )}

          <div className="edit-prompt">
            <label htmlFor="edit-prompt-input">Describe the change</label>
            <div className="edit-prompt-row">
              <textarea
                id="edit-prompt-input"
                value={prompt}
                onChange={e => setPrompt(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="e.g. Add more space between the products"
                rows={2}
                disabled={loading}
              />
              <button
                className="btn-apply-edit"
                onClick={() => handleEdit()}
                disabled={loading || !prompt.trim()}
              >
                {loading ? <><span className="spinner-sm"></span> Applying</> : 'Apply edit'}
              </button>
            </div>
            <div className="suggestion-chips">
              {SUGGESTIONS.map(s => (
                <button key={s.label} onClick={() => setPrompt(s.prompt)} disabled={loading}>{s.label}</button>
              ))}
            </div>
            <p className="prompt-hint">Edits build on each other · Ctrl/⌘ + Enter to apply · Esc to close</p>
          </div>

          {editHistory.length > 0 && (
            <div className="edit-history">
              <p>Edits applied ({editHistory.length})</p>
              <ol>
                {editHistory.map((h, i) => (
                  <li key={i}><span className="edit-history-time">{h.time}</span> {h.prompt}</li>
                ))}
              </ol>
            </div>
          )}
        </div>

        <footer className="edit-modal-footer">
          <button className="btn-done" onClick={onClose} disabled={busy}>
            {editedImagePath ? 'Keep & close' : 'Close'}
          </button>
          <button
            className="btn-approve"
            onClick={handleApprove}
            disabled={busy || approved}
          >
            {approved ? '✓ Approved' : approving ? 'Approving…' : 'Approve this image'}
          </button>
        </footer>
      </div>
    </div>,
    document.body,
  )
}
