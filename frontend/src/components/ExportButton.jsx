import React, { useState } from 'react'
import { exportApproved, getApproved } from '../api/client.js'

export default function ExportButton({ bundles }) {
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState(null)
  const [approvedCount, setApprovedCount] = useState(0)

  React.useEffect(() => {
    getApproved().then(data => setApprovedCount(data.count || 0)).catch(() => {})
  }, [bundles])

  async function handleExport() {
    setExporting(true)
    setExportError(null)
    try {
      const url = await exportApproved()
      const a = document.createElement('a')
      a.href = url
      a.download = 'approved_bundle_images.zip'
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch (err) {
      setExportError(err.message)
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="export-container">
      {exportError && <span className="export-error">{exportError}</span>}
      <button
        className="export-btn"
        onClick={handleExport}
        disabled={exporting || approvedCount === 0}
        title={approvedCount === 0 ? 'No approved images to export' : `Export ${approvedCount} approved image(s)`}
      >
        {exporting ? '⏳ Exporting…' : `⬇ Export ZIP (${approvedCount})`}
      </button>
    </div>
  )
}