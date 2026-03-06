import { NavLink } from 'react-router-dom';
import { LayoutDashboard, Users, Trello, Sparkles } from 'lucide-react';
import NotificationToggle from './NotificationToggle';
import './Layout.css';

const Layout = ({ children }: { children: React.ReactNode }) => {
    return (
        <div className="app-container">
            <aside className="sidebar glass-panel">
                <div className="sidebar-header">
                    <div className="logo">
                        <Sparkles className="logo-icon" size={28} />
                        <span className="text-gradient">AI CRM</span>
                    </div>
                </div>

                <nav className="sidebar-nav">
                    <NavLink to="/dashboard" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
                        <LayoutDashboard size={20} />
                        <span>Dashboard</span>
                    </NavLink>

                    <NavLink to="/contacts" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
                        <Users size={20} />
                        <span>Contacts</span>
                    </NavLink>

                    <NavLink to="/pipeline" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
                        <Trello size={20} />
                        <span>Pipeline</span>
                    </NavLink>

                    <NavLink to="/find-leads" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''} mt-4 !text-indigo-400 border border-indigo-500/30 hover:bg-indigo-500/10`}>
                        <Sparkles size={20} />
                        <span>Find Leads (AI)</span>
                    </NavLink>
                </nav>

                <div className="sidebar-footer">
                    <NotificationToggle />
                    <div className="user-profile mt-3">
                        <div className="avatar">KC</div>
                        <div className="user-info">
                            <span className="name">Kevin Chou</span>
                            <span className="role">Admin</span>
                        </div>
                    </div>
                </div>
            </aside>

            <main className="main-content">
                {children}
            </main>
        </div>
    );
};

export default Layout;
