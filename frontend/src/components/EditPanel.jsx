import React, { useState } from 'react'
import { editImage } from '../api/client.js'

export default function EditPanel({ bundle, onClose, onUpdate }) {
  const [prompt, setPrompt] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [editedImagePath, setEditedImagePath] = useState(null)
  const [editMethod, setEditMethod] = useState(null)
  const [warnings, setWarnings] = useState([])

  const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

  const currentImage = editedImagePath || bundle.generated_image || bundle.original_image
  const currentImageSrc = currentImage
    ? `${API_BASE}/api/images/${currentImage.split('/').pop()}`
    : null
  const originalSrc = bundle.original_image
    ? `${API_BASE}/api/images/${bundle.original_image.split('/').pop()}`
    : null

  async function handleEdit() {
    if (!prompt.trim()) return
    setLoading(true)
    setError(null)
    setWarnings([])
    try {
      const imagePath = bundle.generated_image || bundle.original_image
      const referencePaths = (bundle.products || []).map(p => p.image_path).filter(Boolean)
      const result = await editImage(bundle.code, imagePath, prompt, referencePaths)
      setEditedImagePath(result.image_path)
      setEditMethod(result.method)
      if (result.warnings) setWarnings(result.warnings)
      onUpdate({ ...bundle, generated_image: result.image_path })
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
            </div>
          </div>

          {editMethod && (
            <div className="edit-method-info">
              <strong>Last edit method:</strong> {editMethod === 'pil_programmatic' ? 'PIL (programmatic — instant, 100% fidelity)' : 'Gemini AI (Nano Banana 2.1)'}
            </div>
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
              Tip: Press Ctrl/Cmd+Enter to apply
            </div>
          </div>

          {error && (
            <div className="action-error">
              <strong>Edit failed:</strong> {error}
              <button onClick={handleEdit}>Retry</button>
            </div>
          )}

          <div className="edit-panel-actions">
            <button
              className="btn-apply-edit"
              onClick={handleEdit}
              disabled={loading || !prompt.trim()}
            >
              {loading ? (
                <>
                  <span className="spinner-sm"></span> Applying edit…
                </>
              ) : 'Apply Edit'}
            </button>
            <button
              className="btn-done"
              onClick={onClose}
              disabled={loading}
            >
              Done
            </button>
          </div>

          <div className="edit-suggestions">
            <p><strong>Quick suggestions:</strong></p>
            <div className="suggestion-chips">
              <button onClick={() => setPrompt('Add more space between the products')}>Add more space</button>
              <button onClick={() => setPrompt('Make the products slightly smaller')}>Make smaller</button>
              <button onClick={() => setPrompt('Make the products slightly bigger')}>Make bigger</button>
              <button onClick={() => setPrompt('Center the products in the image')}>Center</button>
              <button onClick={() => setPrompt('Reduce the gap between the products')}>Reduce gap</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}