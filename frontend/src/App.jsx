import React, { useState, useEffect, useRef } from 'react'
import Dashboard from './components/Dashboard.jsx'
import TabBar from './components/TabBar.jsx'
import ExportButton from './components/ExportButton.jsx'
import { fetchBundles, checkHealth } from './api/client.js'

export default function App() {
  const [bundles, setBundles] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [progress, setProgress] = useState(null)
  const [liveTotal, setLiveTotal] = useState(0)
  const [activeTab, setActiveTab] = useState('ready')
  const [backendOnline, setBackendOnline] = useState(false)
  const pollRef = useRef(null)

  // Poll the backend health every few seconds so the badge recovers once a
  // cold-started instance wakes up (the free tier can take ~50s).
  useEffect(() => {
    let active = true
    async function check() {
      const healthy = await checkHealth()
      if (active) setBackendOnline(healthy)
    }
    check()
    const id = setInterval(check, 5000)
    return () => { active = false; clearInterval(id) }
  }, [])

  // Kick off the initial load; clean up any pending poll on unmount.
  useEffect(() => {
    loadBundles(false)
    return () => { if (pollRef.current) clearTimeout(pollRef.current) }
  }, [])

  function clearPoll() {
    if (pollRef.current) { clearTimeout(pollRef.current); pollRef.current = null }
  }

  // The backend loads bundles in the background and reports progress. We poll
  // until it reports "ready" (or "error").
  async function poll(refresh) {
    try {
      const data = await fetchBundles(refresh)
      if (data.status === 'ready') {
        setBundles(data.bundles || [])
        setLiveTotal(data.live_total || (data.bundles || []).length)
        setProgress(null)
        setLoading(false)
        setError(null)
        clearPoll()
      } else if (data.status === 'error') {
        setError(data.error || 'Failed to load bundles')
        setProgress(null)
        setLoading(false)
        clearPoll()
      } else {
        // still loading — show progress and poll again shortly
        setProgress(data)
        setLoading(true)
        pollRef.current = setTimeout(() => poll(false), 2000)
      }
    } catch (err) {
      setError(err.message)
      setLoading(false)
      clearPoll()
    }
  }

  function loadBundles(refresh = false) {
    setError(null)
    setLoading(true)
    clearPoll()
    poll(refresh)
  }

  // Categorize bundles into the three dashboard sections
  const readyBundles = bundles.filter(b => b.category === 'ready')
  const supplierBundles = bundles.filter(b => b.category === 'supplier')
  const manualBundles = bundles.filter(b => b.category === 'manual')

  const tabCounts = {
    ready: readyBundles.length,
    supplier: supplierBundles.length,
    manual: manualBundles.length,
  }

  const currentBundles = activeTab === 'ready' ? readyBundles
    : activeTab === 'supplier' ? supplierBundles
    : manualBundles

  // Rough estimate of time remaining during the crawl phase
  let etaText = ''
  if (progress && progress.total > 0 && progress.processed > 0) {
    const rate = progress.elapsed_seconds / progress.processed
    const remaining = Math.max(0, Math.round(rate * (progress.total - progress.processed)))
    etaText = ` · ~${remaining}s remaining`
  }
  const pct = progress && progress.total > 0
    ? Math.round((100 * progress.processed) / progress.total)
    : null

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-left">
          <h1>Boots Bundle Image Studio</h1>
          <div className={`health-badge ${backendOnline ? 'online' : 'offline'}`}>
            <span className="health-dot"></span>
            {backendOnline ? 'Backend Connected' : 'Backend Offline'}
          </div>
        </div>
        <div className="header-right">
          <ExportButton bundles={bundles} />
          <button
            className="refresh-btn"
            onClick={() => loadBundles(true)}
            disabled={loading}
          >
            {loading ? 'Loading…' : '↻ Refresh'}
          </button>
        </div>
      </header>

      <TabBar activeTab={activeTab} onTabChange={setActiveTab} counts={tabCounts} />

      {!loading && bundles.length > 0 && (
        <div className="summary-bar">
          <strong>{bundles.length}</strong> need action
          {tabCounts.supplier > 0 && <> · {tabCounts.supplier} supplier</>}
          {tabCounts.manual > 0 && <> · {tabCounts.manual} manual review</>}
          {liveTotal > bundles.length && (
            <> · {liveTotal - bundles.length} fine (hidden)</>
          )}
        </div>
      )}

      <main className="app-main">
        {error && (
          <div className="error-banner">
            <strong>Error:</strong> {error}
            <button onClick={() => loadBundles(true)}>Retry</button>
          </div>
        )}

        {loading && bundles.length === 0 ? (
          <div className="loading-state">
            <div className="spinner"></div>
            <p>{progress?.phase || 'Fetching bundles from Monday.com…'}</p>
            {pct !== null ? (
              <div className="progress-wrap">
                <div className="progress-bar">
                  <div className="progress-fill" style={{ width: `${pct}%` }}></div>
                </div>
                <p className="progress-text">
                  {progress.processed} / {progress.total} bundles processed
                  {progress.live_total ? ` · ${progress.live_total.toLocaleString()} confirmed live` : ''}
                </p>
              </div>
            ) : (
              <p className="progress-text">
                Downloading data from Monday.com (large file — this can take ~1 minute)…
              </p>
            )}
            {progress && (
              <p className="progress-elapsed">
                Elapsed {Math.round(progress.elapsed_seconds)}s{etaText}
              </p>
            )}
          </div>
        ) : currentBundles.length === 0 ? (
          <div className="empty-state">
            <p>No bundles in this category.</p>
          </div>
        ) : (
          <Dashboard
            bundles={currentBundles}
            activeTab={activeTab}
            onUpdate={(updatedBundle) => {
              setBundles(prev => prev.map(b =>
                b.code === updatedBundle.code ? updatedBundle : b
              ))
            }}
          />
        )}
      </main>

      <footer className="app-footer">
        <span>Boots Bundle Image Studio v1.0</span>
        <span>Product Enrichment Team</span>
      </footer>
    </div>
  )
}
