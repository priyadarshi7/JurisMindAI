import { Route, Routes } from 'react-router-dom'
import { Header } from './components/Header'
import { Sidebar } from './components/Sidebar'
import { DashboardRoute } from './routes/DashboardRoute'
import { NewResearchRoute } from './routes/NewResearchRoute'
import { ResearchRoute } from './routes/ResearchRoute'
import { HistoryRoute } from './routes/HistoryRoute'
import { SavedRoute } from './routes/SavedRoute'

function App() {
  return (
    <div className="flex h-screen flex-col">
      <Header />
      <div className="flex min-h-0 flex-1">
        <Sidebar />
        <main className="min-w-0 flex-1 overflow-y-auto">
          <Routes>
            <Route path="/" element={<DashboardRoute />} />
            <Route path="/research/new" element={<NewResearchRoute />} />
            <Route path="/research/:jobId" element={<ResearchRoute />} />
            <Route path="/history" element={<HistoryRoute />} />
            <Route path="/saved" element={<SavedRoute />} />
          </Routes>
        </main>
      </div>
    </div>
  )
}

export default App
