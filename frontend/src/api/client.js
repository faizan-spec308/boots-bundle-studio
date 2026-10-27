/**
 * API Client — handles all communication with the FastAPI backend.
 * Base URL is configurable via VITE_API_URL environment variable.
 */

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

/**
 * Fetch all bundles from the backend.
 * Returns categorized bundles: ready, supplier, manual.
 */
export async function fetchBundles(refresh = false) {
  const url = `${API_BASE}/api/bundles${refresh ? '?refresh=true' : ''}`
  const res = await fetch(url)
  if (!res.ok) throw new Error(`Failed to fetch bundles: ${res.statusText}`)
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
  if (!res.ok) throw new Error(`Generation failed: ${res.statusText}`)
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
  if (!res.ok) throw new Error(`Edit failed: ${res.statusText}`)
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
  if (!res.ok) throw new Error(`Approve failed: ${res.statusText}`)
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
  if (!res.ok) throw new Error(`Reject failed: ${res.statusText}`)
  return res.json()
}

/**
 * Export all approved images as a ZIP file.
 * Returns a blob URL for download.
 */
export async function exportApproved() {
  const res = await fetch(`${API_BASE}/api/export`)
  if (!res.ok) throw new Error(`Export failed: ${res.statusText}`)
  const blob = await res.blob()
  return URL.createObjectURL(blob)
}

/**
 * Get list of all approved bundles.
 */
export async function getApproved() {
  const res = await fetch(`${API_BASE}/api/approved`)
  if (!res.ok) throw new Error(`Failed to get approved: ${res.statusText}`)
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
  if (!res.ok) throw new Error(`Upload failed: ${res.statusText}`)
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