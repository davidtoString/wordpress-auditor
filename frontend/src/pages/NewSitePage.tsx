import React from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { sites as sitesApi } from '../lib/api'
import type { SiteCreateInput } from '../lib/types'
import SiteForm from '../components/SiteForm'
import toast from 'react-hot-toast'

export const NewSitePage: React.FC = () => {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const createMutation = useMutation({
    mutationFn: (data: SiteCreateInput) => sitesApi.create(data),
    onSuccess: (newSite) => {
      toast.success(`Successfully registered site: ${newSite.name}`)
      if (newSite.url_redirect_warning) {
        toast(newSite.url_redirect_warning, { icon: '⚠️', duration: 12000 })
      }
      queryClient.invalidateQueries({ queryKey: ['sites'] })
      navigate(`/sites/${newSite.id}`)
    },
    onError: (err: any) => {
      toast.error(err.response?.data?.detail || 'Failed to create site')
    },
  })

  return (
    <SiteForm
      title="Add New WordPress Site"
      subtitle="Register a new WordPress target domain for automated audit schedules, SEO, security, and performance tracking."
      onSubmit={async (values) => {
        await createMutation.mutateAsync(values)
      }}
      isSubmitting={createMutation.isPending}
    />
  )
}

export default NewSitePage
