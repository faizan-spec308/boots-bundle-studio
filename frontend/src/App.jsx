import React, { useState, useEffect } from 'react'
import Dashboard from './components/Dashboard.jsx'
import TabBar from './components/TabBar.jsx'
import ExportButton from './components/ExportButton.jsx'
import { fetchBundles, checkHealth } from './api/client.js'

export default function App() {
  const [bundles, setBundles] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [activeTab, setActiveTab] = useState('ready')
  const [backendOnline, setBackendOnline] = useState(false)

  useEffect(() => {
    loadBundles()
    checkBackendHealth()
  }, [])

  async function checkBackendHealth() {
    const healthy = await checkHealth()
    setBackendOnline(healthy)
  }

  async function loadBundles(refresh = false) {
    setLoading(true)
    setError(null)
    try {
      const data = await fetchBundles(refresh)
      setBundles(data.bundles || [])
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
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
            <p>Fetching bundles from Monday.com and Boots.com…</p>
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