import React, { createContext, useContext, useState, useEffect, useCallback } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { auth as authApi } from './api'
import type { User, AuthTokens } from './types'
import toast from 'react-hot-toast'

export const TOKEN_KEY = 'access_token'
export const REFRESH_TOKEN_KEY = 'refresh_token'
export const USER_KEY = 'wp_auditor_user'

export const getToken = (): string | null => {
  return localStorage.getItem(TOKEN_KEY) || localStorage.getItem('token')
}

export const setTokens = (tokens: AuthTokens) => {
  if (tokens.access_token) {
    localStorage.setItem(TOKEN_KEY, tokens.access_token)
    localStorage.setItem('token', tokens.access_token)
  }
  if (tokens.refresh_token) {
    localStorage.setItem(REFRESH_TOKEN_KEY, tokens.refresh_token)
  }
  if (tokens.user) {
    localStorage.setItem(USER_KEY, JSON.stringify(tokens.user))
  }
}

export const removeTokens = () => {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem('token')
  localStorage.removeItem(REFRESH_TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

interface AuthContextType {
  user: User | null
  token: string | null
  isAuthenticated: boolean
  isAdmin: boolean
  isLoading: boolean
  login: (email: string, password: string) => Promise<User>
  logout: () => void
  updateUser: (updatedUser: Partial<User>) => void
  refreshProfile: () => Promise<void>
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(() => {
    const saved = localStorage.getItem(USER_KEY)
    if (saved) {
      try {
        return JSON.parse(saved)
      } catch {
        return null
      }
    }
    return null
  })
  const [token, setToken] = useState<string | null>(getToken())
  const [isLoading, setIsLoading] = useState<boolean>(true)

  const refreshProfile = useCallback(async () => {
    const currentToken = getToken()
    if (!currentToken) {
      setUser(null)
      setIsLoading(false)
      return
    }

    try {
      const me = await authApi.getMe()
      setUser(me)
      localStorage.setItem(USER_KEY, JSON.stringify(me))
    } catch (err: any) {
      console.warn('Failed to fetch current user profile:', err)
      // Only clear if 401
      if (err?.response?.status === 401) {
        removeTokens()
        setUser(null)
        setToken(null)
      }
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    refreshProfile()
  }, [refreshProfile])

  const login = async (email: string, password: string): Promise<User> => {
    setIsLoading(true)
    try {
      const authData = await authApi.login(email, password)
      setTokens(authData)
      setToken(authData.access_token)

      let currentUser = authData.user
      if (!currentUser) {
        try {
          currentUser = await authApi.getMe()
        } catch {
          // fallback if getMe isn't ready
          currentUser = {
            id: '1',
            email,
            full_name: email.split('@')[0],
            role: email.includes('admin') ? 'admin' : 'viewer',
            is_active: true,
            created_at: new Date().toISOString(),
          }
        }
      }

      setUser(currentUser)
      localStorage.setItem(USER_KEY, JSON.stringify(currentUser))
      toast.success(`Welcome back, ${currentUser.full_name || currentUser.email}!`)
      return currentUser
    } catch (error: any) {
      const msg = error.response?.data?.detail || error.response?.data?.message || 'Invalid email or password'
      toast.error(msg)
      throw error
    } finally {
      setIsLoading(false)
    }
  }

  const logout = () => {
    removeTokens()
    setUser(null)
    setToken(null)
    toast.success('Signed out successfully')
  }

  const updateUser = (updatedUser: Partial<User>) => {
    if (!user) return
    const merged = { ...user, ...updatedUser }
    setUser(merged)
    localStorage.setItem(USER_KEY, JSON.stringify(merged))
  }

  const value: AuthContextType = {
    user,
    token,
    isAuthenticated: !!token && !!user,
    isAdmin: user?.role === 'admin',
    isLoading,
    login,
    logout,
    updateUser,
    refreshProfile,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export const useAuth = () => {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}

export const ProtectedRoute: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { isAuthenticated, isLoading } = useAuth()
  const location = useLocation()

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50 dark:bg-slate-950">
        <div className="flex flex-col items-center gap-3">
          <div className="w-10 h-10 border-4 border-brand-500 border-t-transparent rounded-full animate-spin"></div>
          <p className="text-sm text-slate-500 dark:text-slate-400 font-medium">Verifying session...</p>
        </div>
      </div>
    )
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />
  }

  return <>{children}</>
}

export const AdminRoute: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { isAuthenticated, isAdmin, isLoading } = useAuth()
  const location = useLocation()

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50 dark:bg-slate-950">
        <div className="flex flex-col items-center gap-3">
          <div className="w-10 h-10 border-4 border-brand-500 border-t-transparent rounded-full animate-spin"></div>
          <p className="text-sm text-slate-500 dark:text-slate-400 font-medium">Checking permissions...</p>
        </div>
      </div>
    )
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />
  }

  if (!isAdmin) {
    toast.error('Admin permissions required to access this page')
    return <Navigate to="/dashboard" replace />
  }

  return <>{children}</>
}
