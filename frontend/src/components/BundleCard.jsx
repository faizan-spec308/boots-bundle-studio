import React, { useState } from 'react'
import EditPanel from './EditPanel.jsx'
import { approveImage, rejectImage, generateImage } from '../api/client.js'

export default function BundleCard({ bundle, activeTab, onUpdate }) {
  const [showEdit, setShowEdit] = useState(false)
  const [actionLoading, setActionLoading] = useState(false)
  const [actionError, setActionError] = useState(null)
  const [approved, setApproved] = useState(false)
  const [regenerating, setRegenerating] = useState(false)
  const [imgVersion, setImgVersion] = useState(0)  // cache-bust generated image on change

  const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'
  const originalSrc = bundle.original_image
    ? `${API_BASE}/api/images/${bundle.original_image.split('/').pop()}`
    : null
  const generatedSrc = bundle.generated_image
    ? `${API_BASE}/api/images/${bundle.generated_image.split('/').pop()}?v=${imgVersion}`
    : null

  async function handleApprove() {
    setActionLoading(true)
    setActionError(null)
    try {
      const imagePath = bundle.generated_image || bundle.original_image
      await approveImage(bundle.code, imagePath, bundle.title)
      setApproved(true)
    } catch (err) {
      setActionError(err.message)
    } finally {
      setActionLoading(false)
    }
  }

  async function handleReject() {
    setActionLoading(true)
    setActionError(null)
    try {
      await rejectImage(bundle.code, 'Quality issues — needs manual review')
      onUpdate({ ...bundle, category: 'manual' })
    } catch (err) {
      setActionError(err.message)
    } finally {
      setActionLoading(false)
    }
  }

  async function handleRegenerate() {
    setRegenerating(true)
    setActionError(null)
    try {
      const productPaths = (bundle.products || []).map(p => p.image_path).filter(Boolean)
      const quantities = (bundle.products || []).map(p => p.quantity || 1)
      const result = await generateImage(bundle.code, productPaths, quantities)
      setImgVersion(v => v + 1)  // force the browser to load the new image
      onUpdate({ ...bundle, generated_image: result.image_path })
    } catch (err) {
      setActionError(err.message)
    } finally {
      setRegenerating(false)
    }
  }

  return (
    <div className="bundle-card">
      <div className="bundle-card-header">
        <div className="bundle-title">
          <h3>{bundle.title || 'Untitled Bundle'}</h3>
          <span className="bundle-code">{bundle.code}</span>
        </div>
        {bundle.quality_score !== undefined && (
          <div className={`quality-score ${bundle.quality_score >= 0.7 ? 'good' : 'poor'}`}>
            Quality: {Math.round(bundle.quality_score * 100)}%
          </div>
        )}
      </div>

      {bundle.quality_issues && bundle.quality_issues.length > 0 && (
        <div className="quality-issues">
          <strong>Issues:</strong>
          <ul>
            {bundle.quality_issues.map((issue, i) => (
              <li key={i}>{issue}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="image-comparison">
        <div className="image-side">
          <h4>Original (Boots.com)</h4>
          {originalSrc ? (
            <img src={originalSrc} alt="Original bundle image" />
          ) : (
            <div className="no-image">No image available</div>
          )}
        </div>
        <div className="image-side">
          <h4>Generated</h4>
          {generatedSrc ? (
            <img src={generatedSrc} alt="Generated bundle image" />
          ) : (
            <div className="no-image">
              {regenerating ? 'Generating…' : 'Not yet generated'}
            </div>
          )}
        </div>
      </div>

      {bundle.arrangement_reasoning && (
        <div className="arrangement-info">
          <em>Arrangement: {bundle.arrangement_reasoning}</em>
        </div>
      )}

      {actionError && (
        <div className="action-error">{actionError}</div>
      )}

      <div className="bundle-actions">
        {activeTab === 'ready' && (
          <>
            <button
              className="btn-approve"
              onClick={handleApprove}
              disabled={actionLoading || approved}
            >
              {approved ? '✓ Approved' : actionLoading ? '…' : 'Approve'}
            </button>
            <button
              className="btn-edit"
              onClick={() => setShowEdit(true)}
              disabled={actionLoading}
            >
              Edit Image
            </button>
            <button
              className="btn-regenerate"
              onClick={handleRegenerate}
              disabled={actionLoading || regenerating}
            >
              {regenerating ? 'Generating…' : '↻ Regenerate'}
            </button>
            <button
              className="btn-reject"
              onClick={handleReject}
              disabled={actionLoading}
            >
              Send to Manual Review
            </button>
          </>
        )}
        {activeTab === 'supplier' && (
          <>
            <button
              className="btn-approve"
              onClick={handleApprove}
              disabled={actionLoading || approved}
            >
              {approved ? '✓ Approved' : 'Approve Supplier Image'}
            </button>
            <button
              className="btn-edit"
              onClick={() => setShowEdit(true)}
              disabled={actionLoading}
            >
              Edit Image
            </button>
          </>
        )}
        {activeTab === 'manual' && (
          <>
            <button
              className="btn-regenerate"
              onClick={handleRegenerate}
              disabled={actionLoading || regenerating}
            >
              {regenerating ? 'Generating…' : '↻ Try Generate'}
            </button>
            <button
              className="btn-edit"
              onClick={() => setShowEdit(true)}
              disabled={actionLoading}
            >
              Edit Image
            </button>
          </>
        )}
      </div>

      {showEdit && (
        <EditPanel
          bundle={bundle}
          onClose={() => setShowEdit(false)}
          onUpdate={(updated) => {
            onUpdate(updated)
            setShowEdit(false)
          }}
        />
      )}
    </div>
  )
}