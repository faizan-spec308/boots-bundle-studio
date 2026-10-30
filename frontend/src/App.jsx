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
  const [tipIndex, setTipIndex] = useState(0)
  const [waking, setWaking] = useState(false)
  const pollRef = useRef(null)
  const loadStartRef = useRef(0)
  const failCountRef = useRef(0)

  // The backend (Render free tier) spins down when idle and can take ~50s to
  // wake. We keep retrying the first fetch through that window instead of
  // failing instantly, which is what caused "Failed to fetch" on Vercel.
  const COLD_START_WINDOW_MS = 90000

  // Light status lines that rotate under the real phase while loading, so the
  // wait feels alive rather than frozen. Professional, with a bit of character.
  const DOWNLOAD_TIPS = [
    'Waking up Monday.com and asking nicely for the data…',
    'Fetching a rather large spreadsheet — worth the wait…',
    'Cross-referencing the live bundles (matchmaking, basically)…',
    'Good things take about a minute…',
  ]
  const PROCESS_TIPS = [
    'Tracking down clean product photos on Boots.com…',
    'Asking the AI to spot sneaky multiplier badges…',
    'Measuring each product so nothing comes out supersized…',
    'Giving every product a little room to breathe…',
    'Quietly skipping the bundles that are already perfect…',
    'Rebuilding only what actually needs a touch-up…',
  ]

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

  // Rotate the light status line every few seconds while loading.
  useEffect(() => {
    if (!loading) return
    const id = setInterval(() => setTipIndex(i => i + 1), 3200)
    return () => clearInterval(id)
  }, [loading])

  function clearPoll() {
    if (pollRef.current) { clearTimeout(pollRef.current); pollRef.current = null }
  }

  // The backend loads bundles in the background and reports progress. We poll
  // until it reports "ready" (or "error").
  async function poll(refresh) {
    try {
      const data = await fetchBundles(refresh)
      failCountRef.current = 0
      setWaking(false)
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
      // Network error — most often the backend is still cold-starting. Keep
      // retrying (with backoff) until the wake-up window elapses, rather than
      // failing on the very first attempt.
      const elapsed = Date.now() - loadStartRef.current
      if (elapsed < COLD_START_WINDOW_MS) {
        failCountRef.current += 1
        setWaking(true)
        setLoading(true)
        const backoff = Math.min(2000 + failCountRef.current * 1000, 6000)
        pollRef.current = setTimeout(() => poll(refresh), backoff)
      } else {
        setWaking(false)
        setError(
          "Can't reach the backend. It may be starting up (the free server sleeps " +
          "when idle) — wait a moment and hit Refresh.",
        )
        setLoading(false)
        clearPoll()
      }
    }
  }

  function loadBundles(refresh = false) {
    setError(null)
    setLoading(true)
    setWaking(false)
    failCountRef.current = 0
    loadStartRef.current = Date.now()
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
            <p className="loading-phase">
              {waking ? 'Waking up the server…' : (progress?.phase || 'Getting things ready…')}
            </p>
            <p className="loading-tip" key={waking ? 'waking' : tipIndex}>
              {waking
                ? 'The free server sleeps when idle — this first wake-up can take up to a minute.'
                : (pct !== null ? PROCESS_TIPS : DOWNLOAD_TIPS)[
                    tipIndex % (pct !== null ? PROCESS_TIPS.length : DOWNLOAD_TIPS.length)
                  ]}
            </p>
            {pct !== null && (
              <div className="progress-wrap">
                <div className="progress-bar">
                  <div className="progress-fill" style={{ width: `${pct}%` }}></div>
                </div>
                <p className="progress-text">
                  {progress.found ?? progress.processed} of ~{progress.total} bundles to review found
                  {progress.scanned ? ` · ${progress.scanned} checked` : ''}
                  {progress.live_total ? ` · ${progress.live_total.toLocaleString()} live` : ''}
                </p>
              </div>
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
