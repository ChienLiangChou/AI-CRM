import { NavLink } from 'react-router-dom';
import { LayoutDashboard, Users, Trello, Sparkles } from 'lucide-react';
import NotificationToggle from './NotificationToggle';
import './Layout.css';

const navItems = [
    { to: '/dashboard', icon: LayoutDashboard, label: 'Dashboard' },
    { to: '/contacts', icon: Users, label: 'Contacts' },
    { to: '/pipeline', icon: Trello, label: 'Pipeline' },
    { to: '/find-leads', icon: Sparkles, label: 'Leads' },
    { to: '/agents', icon: Sparkles, label: 'Agents' },
];

const Layout = ({ children }: { children: React.ReactNode }) => {
    return (
        <div className="app-container">
            {/* Desktop sidebar */}
            <aside className="sidebar glass-panel desktop-only">
                <div className="sidebar-header">
                    <div className="logo">
                        <Sparkles className="logo-icon" size={28} />
                        <span className="text-gradient">SKC Agent OS</span>
                    </div>
                </div>

                <nav className="sidebar-nav">
                    {navItems.map(({ to, icon: Icon, label }) => (
                        <NavLink key={to} to={to} className={({ isActive }) =>
                            `nav-item ${isActive ? 'active' : ''}${to === '/find-leads' ? ' mt-4 !text-indigo-400 border border-indigo-500/30 hover:bg-indigo-500/10' : ''}`
                        }>
                            <Icon size={20} />
                            <span>{label}</span>
                        </NavLink>
                    ))}
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

            {/* Mobile top bar */}
            <header className="mobile-topbar mobile-only">
                <div className="logo">
                    <Sparkles className="logo-icon" size={20} />
                    <span className="text-gradient text-lg font-extrabold">SKC Agent OS</span>
                </div>
                <NotificationToggle />
            </header>

            <main className="main-content">
                {children}
            </main>

            {/* Mobile bottom tab bar */}
            <nav className="mobile-tab-bar mobile-only">
                {navItems.map(({ to, icon: Icon, label }) => (
                    <NavLink key={to} to={to} className={({ isActive }) =>
                        `tab-item ${isActive ? 'tab-active' : ''}`
                    }>
                        <Icon size={20} />
                        <span>{label}</span>
                    </NavLink>
                ))}
            </nav>
        </div>
    );
};

export default Layout;
