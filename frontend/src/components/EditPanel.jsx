import React, { useState } from 'react'
import { editImage } from '../api/client.js'

export default function EditPanel({ bundle, onClose, onUpdate }) {
  const [prompt, setPrompt] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [editedImagePath, setEditedImagePath] = useState(null)
  const [warnings, setWarnings] = useState([])
  const [editHistory, setEditHistory] = useState([])
  const [justApplied, setJustApplied] = useState(false)

  const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

  const currentImage = editedImagePath || bundle.generated_image || bundle.original_image
  // Cache-bust with the edit count so successive edits (same filename) visibly update.
  const currentImageSrc = currentImage
    ? `${API_BASE}/api/images/${currentImage.split('/').pop()}?v=${editHistory.length}`
    : null
  const originalSrc = bundle.original_image
    ? `${API_BASE}/api/images/${bundle.original_image.split('/').pop()}`
    : null

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

  function handleKeyDown(e) {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      handleEdit()
    }
  }

  const lastPrompt = editHistory.length ? editHistory[editHistory.length - 1].prompt : ''

  return (
    <div className="edit-panel-overlay" onClick={onClose}>
      <div className="edit-panel" onClick={e => e.stopPropagation()}>
        <div className="edit-panel-header">
          <h2>Edit Image — {bundle.code}</h2>
          <button className="close-btn" onClick={onClose}>✕</button>
        </div>

        <div className="edit-panel-body">
          <div className="edit-comparison">
            <div className="edit-image-side">
              <h4>Original</h4>
              {originalSrc ? (
                <img src={originalSrc} alt="Original" />
              ) : (
                <div className="no-image">No original</div>
              )}
            </div>
            <div className="edit-image-side">
              <h4>Current</h4>
              {currentImageSrc ? (
                <img src={currentImageSrc} alt="Current" />
              ) : (
                <div className="no-image">No image</div>
              )}
              {loading && (
                <div className="edit-loading-overlay">
                  <div className="spinner"></div>
                  <p>Applying edit via Gemini AI…</p>
                </div>
              )}
            </div>
          </div>

          {justApplied && !loading && (
            <div className="edit-applied">✓ Edit applied — “{lastPrompt}”</div>
          )}

          {warnings.length > 0 && (
            <div className="edit-warnings">
              <strong>⚠ Fidelity warnings:</strong>
              <ul>
                {warnings.map((w, i) => <li key={i}>{w}</li>)}
              </ul>
            </div>
          )}

          <div className="edit-prompt-area">
            <label htmlFor="edit-prompt">Enter edit instructions:</label>
            <textarea
              id="edit-prompt"
              value={prompt}
              onChange={e => setPrompt(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="e.g. Add more space between the products and make them slightly smaller"
              rows={3}
              disabled={loading}
            />
            <div className="prompt-hint">
              Edits use Gemini AI and build on each other. Tip: Ctrl/Cmd+Enter to apply.
            </div>
          </div>

          {error && (
            <div className="action-error">
              <strong>Edit failed:</strong> {error}
              <button onClick={() => handleEdit(lastPrompt || undefined)} disabled={loading}>Retry</button>
            </div>
          )}

          <div className="edit-panel-actions">
            <button
              className="btn-apply-edit"
              onClick={() => handleEdit()}
              disabled={loading || !prompt.trim()}
            >
              {loading ? (
                <><span className="spinner-sm"></span> Applying…</>
              ) : 'Apply Edit'}
            </button>
            <button className="btn-done" onClick={onClose} disabled={loading}>
              Done
            </button>
          </div>

          {editHistory.length > 0 && (
            <div className="edit-history">
              <p><strong>Edits applied ({editHistory.length}):</strong></p>
              <ol>
                {editHistory.map((h, i) => (
                  <li key={i}><span className="edit-history-time">{h.time}</span> {h.prompt}</li>
                ))}
              </ol>
            </div>
          )}

          <div className="edit-suggestions">
            <p><strong>Quick suggestions:</strong></p>
            <div className="suggestion-chips">
              <button onClick={() => setPrompt('Add more space between the products')}>Add more space</button>
              <button onClick={() => setPrompt('Make the products slightly bigger')}>Make bigger</button>
              <button onClick={() => setPrompt('Make the products slightly smaller')}>Make smaller</button>
              <button onClick={() => setPrompt('Center the products in the image')}>Center products</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
