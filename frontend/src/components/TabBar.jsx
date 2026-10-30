import React from 'react'

export default function TabBar({ activeTab, onTabChange, counts }) {
  const tabs = [
    { id: 'ready', label: 'Ready for Approval', count: counts.ready },
    { id: 'supplier', label: 'Supplier Image Required', count: counts.supplier },
    { id: 'manual', label: 'Manual Review Required', count: counts.manual },
  ]

  return (
    <nav className="tab-bar">
      <div className="tab-bar-inner">
        {tabs.map(tab => (
          <button
            key={tab.id}
            data-tab={tab.id}
            className={`tab ${activeTab === tab.id ? 'active' : ''}`}
            onClick={() => onTabChange(tab.id)}
          >
            <span className="tab-label">{tab.label}</span>
            <span className="tab-count">{tab.count}</span>
          </button>
        ))}
      </div>
    </nav>
  )
}