import React from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { sites as sitesApi } from '../lib/api'
import type { SiteUpdateInput } from '../lib/types'
import SiteForm from '../components/SiteForm'
import { Loader2 } from 'lucide-react'
import toast from 'react-hot-toast'

export const EditSitePage: React.FC = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const { data: site, isLoading, isError } = useQuery({
    queryKey: ['site', id],
    queryFn: () => sitesApi.get(id!),
    enabled: !!id,
  })

  const updateMutation = useMutation({
    mutationFn: (data: SiteUpdateInput) => sitesApi.update(id!, data),
    onSuccess: (updated) => {
      toast.success(`Successfully updated site: ${updated.name}`)
      if (updated.url_redirect_warning) {
        toast(updated.url_redirect_warning, { icon: '⚠️', duration: 12000 })
      }
      queryClient.invalidateQueries({ queryKey: ['sites'] })
      queryClient.invalidateQueries({ queryKey: ['site', id] })
      navigate(`/sites/${id}`)
    },
    onError: (err: any) => {
      toast.error(err.response?.data?.detail || 'Failed to update site configuration')
    },
  })

  if (isLoading) {
    return (
      <div className="py-24 flex flex-col items-center justify-center">
        <Loader2 className="w-8 h-8 text-brand-600 animate-spin mb-3" />
        <p className="text-sm text-slate-500">Loading site configuration...</p>
      </div>
    )
  }

  if (isError || !site) {
    return (
      <div className="max-w-md mx-auto text-center py-20">
        <h3 className="text-lg font-bold text-slate-800 dark:text-slate-200">Site Not Found</h3>
        <p className="text-xs text-slate-500 mt-1 mb-4">
          The requested site does not exist or has been removed.
        </p>
        <button
          onClick={() => navigate('/sites')}
          className="px-4 py-2 bg-brand-600 text-white rounded-lg text-sm font-semibold"
        >
          Back to Sites
        </button>
      </div>
    )
  }

  return (
    <SiteForm
      initialValues={site}
      title={`Edit Site: ${site.name}`}
      subtitle="Update domain settings, scheduling cron expressions, authentication, or NAP data."
      onSubmit={async (values) => {
        await updateMutation.mutateAsync(values)
      }}
      isSubmitting={updateMutation.isPending}
    />
  )
}

export default EditSitePage
