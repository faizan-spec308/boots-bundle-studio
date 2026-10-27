import React from 'react'
import BundleCard from './BundleCard.jsx'

export default function Dashboard({ bundles, activeTab, onUpdate }) {
  return (
    <div className="dashboard">
      <div className="dashboard-grid">
        {bundles.map(bundle => (
          <BundleCard
            key={bundle.code}
            bundle={bundle}
            activeTab={activeTab}
            onUpdate={onUpdate}
          />
        ))}
      </div>
    </div>
  )
}