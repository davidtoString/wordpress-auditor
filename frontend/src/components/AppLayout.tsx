import React, { useState } from 'react'
import { Link, NavLink, useLocation, useNavigate, Outlet } from 'react-router-dom'
import {
  LayoutDashboard,
  Globe,
  ClipboardList,
  Users,
  Settings,
  LogOut,
  Moon,
  Sun,
  Play,
  Loader2,
  Menu,
  X,
  User as UserIcon,
} from 'lucide-react'
import { useAuth } from '../lib/auth'
import { useTheme } from '../hooks/useTheme'
import { settings as settingsApi } from '../lib/api'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { cn } from '../lib/utils'

export const AppLayout: React.FC = () => {
  const { user, isAdmin, logout } = useAuth()
  const { theme, toggleTheme } = useTheme()
  const location = useLocation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)

  const runAllMutation = useMutation({
    mutationFn: () => settingsApi.runAll(),
    onSuccess: (data) => {
      toast.success(data.message || 'Audit batch queued for all active sites!')
      queryClient.invalidateQueries({ queryKey: ['sites'] })
      queryClient.invalidateQueries({ queryKey: ['audits'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] })
    },
    onError: (err: any) => {
      toast.error(err.response?.data?.detail || 'Failed to trigger batch audits')
    },
  })

  const getPageTitle = (pathname: string): string => {
    if (pathname.startsWith('/sites/new')) return 'Add New Site'
    if (pathname.match(/\/sites\/[^/]+\/edit/)) return 'Edit Site Configuration'
    if (pathname.startsWith('/sites/')) return 'Site Audit Overview'
    if (pathname.startsWith('/sites')) return 'Managed WordPress Sites'
    if (pathname.startsWith('/audits/')) return 'Audit Run Report'
    if (pathname.startsWith('/audits')) return 'All Audit Runs'
    if (pathname.startsWith('/users')) return 'User & Role Management'
    if (pathname.startsWith('/settings')) return 'Global Configuration'
    if (pathname.startsWith('/profile')) return 'My Account Profile'
    return 'Dashboard'
  }

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  const navItems = [
    { name: 'Dashboard', to: '/dashboard', icon: LayoutDashboard },
    { name: 'Sites', to: '/sites', icon: Globe },
    { name: 'Audits', to: '/audits', icon: ClipboardList },
    ...(isAdmin
      ? [
          { name: 'Users', to: '/users', icon: Users },
          { name: 'Settings', to: '/settings', icon: Settings },
        ]
      : []),
  ]

  const userInitials = user?.full_name
    ? user.full_name
        .split(' ')
        .map((n) => n[0])
        .join('')
        .toUpperCase()
        .slice(0, 2)
    : user?.email?.slice(0, 2).toUpperCase() || 'WP'

  return (
    <div className="flex h-screen w-full bg-slate-50 dark:bg-slate-950 text-slate-900 dark:text-slate-100 overflow-hidden font-sans">
      {/* Mobile Backdrop */}
      {mobileMenuOpen && (
        <div
          className="fixed inset-0 z-40 bg-slate-900/50 backdrop-blur-sm lg:hidden"
          onClick={() => setMobileMenuOpen(false)}
        />
      )}

      {/* Sidebar (240px wide on desktop) */}
      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-50 w-60 bg-white dark:bg-slate-900 border-r border-slate-200 dark:border-slate-800 flex flex-col justify-between transition-transform duration-300 lg:static lg:translate-x-0',
          mobileMenuOpen ? 'translate-x-0' : '-translate-x-full'
        )}
      >
        <div className="flex flex-col h-full">
          {/* Logo Area */}
          <div className="h-16 flex items-center justify-between px-5 border-b border-slate-100 dark:border-slate-800/80">
            <Link
              to="/dashboard"
              className="flex items-center gap-2.5 font-bold text-lg text-slate-900 dark:text-slate-100 tracking-tight hover:opacity-90"
              onClick={() => setMobileMenuOpen(false)}
            >
              <div className="w-8 h-8 rounded-lg bg-brand-600 flex items-center justify-center text-white shadow-sm shadow-brand-500/30">
                <span className="text-base">🔍</span>
              </div>
              <div className="flex flex-col">
                <span className="leading-none text-base">WP Auditor</span>
                <span className="text-[10px] font-medium text-brand-600 dark:text-brand-400 uppercase tracking-wider mt-0.5">
                  Pro Engine
                </span>
              </div>
            </Link>
            <button
              type="button"
              className="lg:hidden p-1.5 rounded-md text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"
              onClick={() => setMobileMenuOpen(false)}
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Navigation Links */}
          <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
            <div className="px-3 pb-2 text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
              Navigation
            </div>
            {navItems.map((item) => {
              const Icon = item.icon
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  onClick={() => setMobileMenuOpen(false)}
                  className={({ isActive }) =>
                    cn(
                      'flex items-center gap-3 px-3.5 py-2.5 rounded-lg text-sm font-medium transition-colors',
                      isActive
                        ? 'bg-brand-500 text-white shadow-sm shadow-brand-500/25 font-semibold'
                        : 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800/70 hover:text-slate-900 dark:hover:text-slate-200'
                    )
                  }
                >
                  <Icon className="w-4 h-4 shrink-0" />
                  <span>{item.name}</span>
                </NavLink>
              )
            })}
          </nav>

          {/* Bottom User Area */}
          <div className="p-3 border-t border-slate-100 dark:border-slate-800/80 bg-slate-50/50 dark:bg-slate-900/50">
            <div className="flex items-center justify-between p-2 rounded-lg hover:bg-white dark:hover:bg-slate-800/80 transition-colors">
              <Link
                to="/profile"
                className="flex items-center gap-2.5 min-w-0 flex-1 group"
                onClick={() => setMobileMenuOpen(false)}
              >
                <div className="w-9 h-9 rounded-full bg-brand-100 dark:bg-brand-950 text-brand-700 dark:text-brand-300 border border-brand-200 dark:border-brand-800 flex items-center justify-center font-bold text-xs shrink-0 group-hover:ring-2 ring-brand-500/30 transition-all">
                  {userInitials}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-semibold text-slate-800 dark:text-slate-200 truncate group-hover:text-brand-600 dark:group-hover:text-brand-400">
                    {user?.full_name || user?.email || 'User'}
                  </p>
                  <div className="flex items-center gap-1.5 mt-0.5">
                    <span
                      className={cn(
                        'text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.2 rounded',
                        isAdmin
                          ? 'bg-purple-100 text-purple-700 dark:bg-purple-950 dark:text-purple-300'
                          : 'bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-300'
                      )}
                    >
                      {user?.role || 'viewer'}
                    </span>
                  </div>
                </div>
              </Link>
              <button
                type="button"
                onClick={handleLogout}
                title="Sign out"
                className="p-1.5 rounded-md text-slate-400 hover:text-rose-600 dark:hover:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-950/30 transition-colors ml-1"
              >
                <LogOut className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Top Header Bar */}
        <header className="h-16 bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800 px-4 sm:px-6 flex items-center justify-between shrink-0 z-10">
          <div className="flex items-center gap-3">
            <button
              type="button"
              className="lg:hidden p-2 rounded-lg text-slate-500 hover:text-slate-800 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800"
              onClick={() => setMobileMenuOpen(true)}
            >
              <Menu className="w-5 h-5" />
            </button>
            <h1 className="text-lg sm:text-xl font-bold text-slate-900 dark:text-slate-100">
              {getPageTitle(location.pathname)}
            </h1>
          </div>

          <div className="flex items-center gap-2 sm:gap-3">
            {/* Run All Audits Button */}
            {isAdmin && (
              <button
                type="button"
                onClick={() => runAllMutation.mutate()}
                disabled={runAllMutation.isPending}
                className="inline-flex items-center gap-1.5 px-3 sm:px-3.5 py-1.5 text-xs sm:text-sm font-semibold text-white bg-brand-600 hover:bg-brand-700 rounded-lg shadow-sm hover:shadow transition-all disabled:opacity-60"
                title="Trigger automated audits for all configured sites"
              >
                {runAllMutation.isPending ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Play className="w-4 h-4 fill-current" />
                )}
                <span className="hidden sm:inline">Run All Audits</span>
                <span className="sm:hidden">Run All</span>
              </button>
            )}

            {/* Dark Mode Toggle */}
            <button
              type="button"
              onClick={toggleTheme}
              className="p-2 rounded-lg text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
              title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            >
              {theme === 'dark' ? (
                <Sun className="w-4 h-4 text-amber-400" />
              ) : (
                <Moon className="w-4 h-4" />
              )}
            </button>

            {/* Profile quick link */}
            <Link
              to="/profile"
              className="p-2 rounded-lg text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
              title="Profile settings"
            >
              <UserIcon className="w-4 h-4" />
            </Link>
          </div>
        </header>

        {/* Page Main Content with Scrolling */}
        <main className="flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8 bg-slate-50 dark:bg-slate-950">
          <div className="max-w-7xl mx-auto">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}

export default AppLayout
