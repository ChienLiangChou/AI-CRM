import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import Contacts from './pages/Contacts';
import Pipeline from './pages/Pipeline';
import Prospector from './pages/Prospector';

function App() {
  return (
    <Router>
      <Layout>
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/contacts" element={<Contacts />} />
          <Route path="/pipeline" element={<Pipeline />} />
          <Route path="/find-leads" element={<Prospector />} />
        </Routes>
      </Layout>
    </Router>
  );
}

export default App;
