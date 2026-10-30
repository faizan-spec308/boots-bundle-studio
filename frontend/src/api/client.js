/**
 * API Client — handles all communication with the FastAPI backend.
 * Base URL is configurable via VITE_API_URL environment variable.
 */

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

/**
 * Build a readable error from a failed response: prefer the backend's own
 * explanation (FastAPI's `detail`) over the bare HTTP status text, so the UI can
 * say e.g. "Gemini credits are used up" instead of "Internal Server Error".
 */
async function errorFrom(res, action) {
  try {
    const body = await res.json()
    if (body && body.detail) {
      return typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    }
  } catch {
    // not JSON — fall through
  }
  return `${action} (${res.status} ${res.statusText})`
}

/**
 * Fetch bundles from the backend (it loads in the background; poll until ready).
 * mode: ''          — current results (or start the first load)
 *       'reprocess' — re-run the latest rules on the bundles already shown
 *       'force'     — scan a NEW batch of bundles
 */
export async function fetchBundles(mode = '') {
  const url = `${API_BASE}/api/bundles${mode ? `?${mode}=true` : ''}`
  const res = await fetch(url)
  if (!res.ok) throw new Error(await errorFrom(res, 'Failed to fetch bundles'))
  return res.json()
}

/**
 * Generate a bundle image from product photos (PIL compositing).
 */
export async function generateImage(bundleCode, productImagePaths, quantities = [], gap = null) {
  const res = await fetch(`${API_BASE}/api/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ bundle_code: bundleCode, product_image_paths: productImagePaths, quantities, gap }),
  })
  if (!res.ok) throw new Error(await errorFrom(res, 'Generation failed'))
  return res.json()
}

/**
 * Edit a bundle image with a natural language prompt.
 * Backend tries PIL first, falls back to Gemini AI.
 */
export async function editImage(bundleCode, imagePath, editPrompt, referenceImagePaths = []) {
  const res = await fetch(`${API_BASE}/api/edit`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      bundle_code: bundleCode,
      image_path: imagePath,
      edit_prompt: editPrompt,
      reference_image_paths: referenceImagePaths,
    }),
  })
  if (!res.ok) throw new Error(await errorFrom(res, 'Edit failed'))
  return res.json()
}

/**
 * Approve a bundle image.
 */
export async function approveImage(bundleCode, imagePath, title = '') {
  const res = await fetch(`${API_BASE}/api/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ bundle_code: bundleCode, image_path: imagePath, title }),
  })
  if (!res.ok) throw new Error(await errorFrom(res, 'Approve failed'))
  return res.json()
}

/**
 * Reject a bundle image (send back to manual review).
 */
export async function rejectImage(bundleCode, reason = '') {
  const res = await fetch(`${API_BASE}/api/reject`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ bundle_code: bundleCode, reason }),
  })
  if (!res.ok) throw new Error(await errorFrom(res, 'Reject failed'))
  return res.json()
}

/**
 * Export all approved images as a ZIP file.
 * Returns a blob URL for download.
 */
export async function exportApproved() {
  const res = await fetch(`${API_BASE}/api/export`)
  if (!res.ok) throw new Error(await errorFrom(res, 'Export failed'))
  const blob = await res.blob()
  return URL.createObjectURL(blob)
}

/**
 * Get list of all approved bundles.
 */
export async function getApproved() {
  const res = await fetch(`${API_BASE}/api/approved`)
  if (!res.ok) throw new Error(await errorFrom(res, 'Failed to get approved'))
  return res.json()
}

/**
 * Upload a supplier-provided image for a bundle.
 */
export async function uploadImage(bundleCode, file) {
  const formData = new FormData()
  formData.append('bundle_code', bundleCode)
  formData.append('file', file)
  const res = await fetch(`${API_BASE}/api/upload`, {
    method: 'POST',
    body: formData,
  })
  if (!res.ok) throw new Error(await errorFrom(res, 'Upload failed'))
  return res.json()
}

/**
 * Build a full URL for an image served by the backend.
 */
export function imageUrl(filename) {
  return `${API_BASE}/api/images/${filename}`
}

/**
 * Check backend health.
 */
export async function checkHealth() {
  try {
    const res = await fetch(`${API_BASE}/healthz`)
    return res.ok
  } catch {
    return false
  }
}