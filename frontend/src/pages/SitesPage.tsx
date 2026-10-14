import React, { useState, useMemo } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Plus,
  Search,
  Play,
  Pencil,
  Trash2,
  ExternalLink,
  Globe,
  Loader2,
  Calendar,
  AlertCircle,
  Filter,
} from 'lucide-react'
import { sites as sitesApi } from '../lib/api'
import { useAuth } from '../lib/auth'
import type { Site } from '../lib/types'
import ScoreBadge from '../components/ScoreBadge'
import Modal from '../components/ui/Modal'
import { formatDate, formatRelative } from '../lib/utils'
import toast from 'react-hot-toast'

export const SitesPage: React.FC = () => {
  const { isAdmin } = useAuth()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const [searchTerm, setSearchTerm] = useState('')
  const [statusFilter, setStatusFilter] = useState<'all' | 'active' | 'inactive' | 'critical'>('all')
  const [siteToDelete, setSiteToDelete] = useState<Site | null>(null)
  const [runningSiteId, setRunningSiteId] = useState<string | null>(null)

  const { data: sitesList = [], isLoading } = useQuery({
    queryKey: ['sites'],
    queryFn: () => sitesApi.list(),
  })

  // Trigger audit mutation
  const triggerAuditMutation = useMutation({
    mutationFn: (id: string) => sitesApi.triggerAudit(id),
    onMutate: (id) => {
      setRunningSiteId(id)
    },
    onSuccess: () => {
      toast.success('Audit triggered successfully!')
      queryClient.invalidateQueries({ queryKey: ['sites'] })
      queryClient.invalidateQueries({ queryKey: ['audits'] })
    },
    onError: (err: any) => {
      toast.error(err.response?.data?.detail || 'Failed to trigger audit')
    },
    onSettled: () => {
      setRunningSiteId(null)
    },
  })

  // Delete site mutation
  const deleteSiteMutation = useMutation({
    mutationFn: (id: string) => sitesApi.delete(id),
    onSuccess: () => {
      toast.success('Site deleted successfully')
      setSiteToDelete(null)
      queryClient.invalidateQueries({ queryKey: ['sites'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] })
    },
    onError: (err: any) => {
      toast.error(err.response?.data?.detail || 'Failed to delete site')
    },
  })

  // Filtered sites
  const filteredSites = useMemo(() => {
    return sitesList.filter((site) => {
      const matchesSearch =
        site.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
        site.url.toLowerCase().includes(searchTerm.toLowerCase())

      if (!matchesSearch) return false

      if (statusFilter === 'active') return site.is_active !== false
      if (statusFilter === 'inactive') return site.is_active === false
      if (statusFilter === 'critical') {
        return site.last_score !== null && site.last_score !== undefined && site.last_score < 50
      }
      return true
    })
  }, [sitesList, searchTerm, statusFilter])

  return (
    <div className="space-y-6 pb-12">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-slate-900 dark:text-slate-100">
            Managed Sites
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-0.5">
            Configure target WordPress websites, automated cron intervals, and audit credentials.
          </p>
        </div>

        {isAdmin && (
          <Link
            to="/sites/new"
            className="inline-flex items-center gap-1.5 px-4 py-2.5 text-sm font-semibold rounded-xl text-white bg-brand-600 hover:bg-brand-700 shadow-sm hover:shadow transition-all"
          >
            <Plus className="w-4 h-4" />
            Add New Site
          </Link>
        )}
      </div>

      {/* Filter / Search Bar */}
      <div className="bg-white dark:bg-slate-800/90 rounded-2xl border border-slate-200 dark:border-slate-700/80 p-4 shadow-sm flex flex-col sm:flex-row items-center justify-between gap-3">
        <div className="relative w-full sm:w-80">
          <Search className="w-4 h-4 absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder="Search by site name or URL..."
            className="w-full pl-9 pr-4 py-2 text-sm rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-slate-100 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-brand-500"
          />
        </div>

        <div className="flex items-center gap-2 w-full sm:w-auto overflow-x-auto">
          <Filter className="w-4 h-4 text-slate-400 hidden sm:block" />
          <button
            type="button"
            onClick={() => setStatusFilter('all')}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
              statusFilter === 'all'
                ? 'bg-brand-500 text-white shadow-sm'
                : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700'
            }`}
          >
            All ({sitesList.length})
          </button>
          <button
            type="button"
            onClick={() => setStatusFilter('active')}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
              statusFilter === 'active'
                ? 'bg-emerald-600 text-white shadow-sm'
                : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700'
            }`}
          >
            Active
          </button>
          <button
            type="button"
            onClick={() => setStatusFilter('inactive')}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
              statusFilter === 'inactive'
                ? 'bg-slate-700 text-white shadow-sm'
                : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700'
            }`}
          >
            Inactive
          </button>
          <button
            type="button"
            onClick={() => setStatusFilter('critical')}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
              statusFilter === 'critical'
                ? 'bg-rose-600 text-white shadow-sm'
                : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700'
            }`}
          >
            Critical (&lt;50)
          </button>
        </div>
      </div>

      {/* Sites Table */}
      <div className="bg-white dark:bg-slate-800/90 rounded-2xl border border-slate-200 dark:border-slate-700/80 shadow-sm overflow-hidden">
        {isLoading ? (
          <div className="p-8 space-y-4">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="animate-pulse flex items-center justify-between py-3 border-b border-slate-100 dark:border-slate-800">
                <div className="space-y-2">
                  <div className="h-4 bg-slate-200 dark:bg-slate-700 rounded w-48" />
                  <div className="h-3 bg-slate-100 dark:bg-slate-800 rounded w-64" />
                </div>
                <div className="h-6 bg-slate-200 dark:bg-slate-700 rounded-full w-16" />
                <div className="h-4 bg-slate-200 dark:bg-slate-700 rounded w-24" />
                <div className="h-8 bg-slate-200 dark:bg-slate-700 rounded w-28" />
              </div>
            ))}
          </div>
        ) : filteredSites.length === 0 ? (
          <div className="p-16 text-center">
            <div className="w-14 h-14 rounded-2xl bg-slate-100 dark:bg-slate-700/50 flex items-center justify-center mx-auto mb-4 text-slate-400">
              <Globe className="w-8 h-8" />
            </div>
            <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100 mb-1">
              No matching WordPress sites found
            </h3>
            <p className="text-xs text-slate-500 max-w-sm mx-auto mb-5">
              {searchTerm
                ? 'Try adjusting your search query or clear filters.'
                : 'Get started by configuring your first WordPress site for continuous auditing.'}
            </p>
            {isAdmin && !searchTerm && (
              <Link
                to="/sites/new"
                className="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-semibold rounded-lg text-white bg-brand-600 hover:bg-brand-700 shadow-sm"
              >
                <Plus className="w-4 h-4" />
                Add WordPress Site
              </Link>
            )}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-sm">
              <thead>
                <tr className="border-b border-slate-200 dark:border-slate-700/80 bg-slate-50/75 dark:bg-slate-900/40 text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  <th className="py-3.5 px-5">Website Details</th>
                  <th className="py-3.5 px-4">Audit Score</th>
                  <th className="py-3.5 px-4">Last Audit</th>
                  <th className="py-3.5 px-4">Cron Schedule</th>
                  <th className="py-3.5 px-4">Status</th>
                  <th className="py-3.5 px-5 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-700/50">
                {filteredSites.map((site) => (
                  <tr
                    key={site.id}
                    className="hover:bg-slate-50/60 dark:hover:bg-slate-700/30 transition-colors"
                  >
                    <td className="py-4 px-5">
                      <div className="font-semibold text-slate-900 dark:text-slate-100 hover:text-brand-600">
                        <Link to={`/sites/${site.id}`}>{site.name}</Link>
                      </div>
                      <a
                        href={site.url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-xs text-slate-400 hover:text-brand-500 inline-flex items-center gap-1 mt-0.5"
                      >
                        {site.url}
                        <ExternalLink className="w-3 h-3" />
                      </a>
                    </td>

                    <td className="py-4 px-4">
                      <ScoreBadge score={site.last_score} showLabel />
                    </td>

                    <td className="py-4 px-4">
                      <div
                        className="text-xs text-slate-700 dark:text-slate-300 font-medium"
                        title={formatDate(site.last_audit_at)}
                      >
                        {formatRelative(site.last_audit_at)}
                      </div>
                    </td>

                    <td className="py-4 px-4">
                      <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-slate-100 dark:bg-slate-800 text-xs font-mono text-slate-700 dark:text-slate-300">
                        <Calendar className="w-3 h-3 text-slate-400" />
                        {site.cron_schedule || '0 6 * * *'}
                      </div>
                    </td>

                    <td className="py-4 px-4">
                      {site.is_active !== false ? (
                        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-100 dark:bg-emerald-950/60 text-emerald-800 dark:text-emerald-300">
                          Active
                        </span>
                      ) : (
                        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400">
                          Disabled
                        </span>
                      )}
                    </td>

                    <td className="py-4 px-5 text-right">
                      <div className="flex items-center justify-end gap-1.5">
                        {/* View */}
                        <button
                          type="button"
                          onClick={() => navigate(`/sites/${site.id}`)}
                          className="px-2.5 py-1 rounded-lg text-xs font-medium text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700/60 transition-colors"
                          title="View Site Audit Dashboard"
                        >
                          View
                        </button>

                        {/* Trigger Audit */}
                        <button
                          type="button"
                          onClick={() => triggerAuditMutation.mutate(site.id)}
                          disabled={runningSiteId === site.id}
                          className="px-2.5 py-1 rounded-lg text-xs font-medium text-brand-600 dark:text-brand-400 bg-brand-50 dark:bg-brand-950/50 hover:bg-brand-100 dark:hover:bg-brand-900/50 transition-colors inline-flex items-center gap-1 disabled:opacity-60"
                          title="Trigger Audit Now"
                        >
                          {runningSiteId === site.id ? (
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          ) : (
                            <Play className="w-3.5 h-3.5 fill-current" />
                          )}
                          Audit
                        </button>

                        {/* Admin actions */}
                        {isAdmin && (
                          <>
                            <button
                              type="button"
                              onClick={() => navigate(`/sites/${site.id}/edit`)}
                              className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700/60 transition-colors"
                              title="Edit Site"
                            >
                              <Pencil className="w-4 h-4" />
                            </button>
                            <button
                              type="button"
                              onClick={() => setSiteToDelete(site)}
                              className="p-1.5 rounded-lg text-slate-400 hover:text-rose-600 dark:hover:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-950/30 transition-colors"
                              title="Delete Site"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Delete Confirmation Modal */}
      <Modal
        isOpen={!!siteToDelete}
        onClose={() => setSiteToDelete(null)}
        title="Confirm Delete Site"
        description="This action cannot be undone. All audit histories for this site will be permanently removed."
      >
        <div className="space-y-4">
          <div className="p-3.5 rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900/60 text-xs text-rose-800 dark:text-rose-300 flex items-start gap-2.5">
            <AlertCircle className="w-4 h-4 text-rose-600 shrink-0 mt-0.5" />
            <div>
              Are you sure you want to delete{' '}
              <strong className="font-semibold text-rose-900 dark:text-rose-200">
                {siteToDelete?.name}
              </strong>{' '}
              ({siteToDelete?.url})?
            </div>
          </div>

          <div className="flex justify-end gap-2.5 pt-2">
            <button
              type="button"
              onClick={() => setSiteToDelete(null)}
              className="px-4 py-2 rounded-xl text-xs font-semibold text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => siteToDelete && deleteSiteMutation.mutate(siteToDelete.id)}
              disabled={deleteSiteMutation.isPending}
              className="px-4 py-2 rounded-xl text-xs font-semibold text-white bg-rose-600 hover:bg-rose-700 shadow-sm transition-colors flex items-center gap-1.5 disabled:opacity-60"
            >
              {deleteSiteMutation.isPending ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Trash2 className="w-3.5 h-3.5" />
              )}
              Confirm Delete
            </button>
          </div>
        </div>
      </Modal>
    </div>
  )
}

export default SitesPage
