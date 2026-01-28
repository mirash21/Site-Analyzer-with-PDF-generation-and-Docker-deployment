import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import axios from 'axios'
import Loader from './components/Loader'
import ResultCard from './components/ResultCard'
import LoginForm from './components/LoginForm'
import Dashboard from './components/Dashboard'
import { API_BASE_URL } from './config'

// Настройка axios для авторизации
const api = axios.create({
  baseURL: API_BASE_URL,
})

// Добавляем токен к каждому запросу
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const [url, setUrl] = useState('')
  const [analyzing, setAnalyzing] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)

  useEffect(() => {
    checkAuth()
  }, [])

  const checkAuth = async () => {
    const token = localStorage.getItem('token')
    if (token) {
      try {
        const response = await api.get('/auth/me')
        setUser(response.data)
        setIsAuthenticated(true)
      } catch (err) {
        localStorage.removeItem('token')
        setIsAuthenticated(false)
      }
    }
    setLoading(false)
  }

  const handleLogin = async (credentials) => {
    try {
      const formData = new FormData()
      formData.append('username', credentials.username)
      formData.append('password', credentials.password)

      const response = await api.post('/auth/login', formData)
      localStorage.setItem('token', response.data.access_token)
      setUser(response.data.user)
      setIsAuthenticated(true)
      return { success: true }
    } catch (err) {
      return {
        success: false,
        error: err.response?.data?.detail || 'Ошибка входа'
      }
    }
  }

  // Регистрация отключена - функция оставлена для совместимости
  const handleRegister = async (userData) => {
    return {
      success: false,
      error: 'Регистрация отключена. Обратитесь к администратору.'
    }
  }

  const handleLogout = () => {
    localStorage.removeItem('token')
    setUser(null)
    setIsAuthenticated(false)
    setResult(null)
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!url.trim()) return

    setAnalyzing(true)
    setError(null)
    setResult(null)

    try {
      const response = await api.post('/llm/analyze-site', {
        url: url.trim()
      })
      setResult(response.data)
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Произошла ошибка при анализе')
    } finally {
      setAnalyzing(false)
    }
  }

  if (loading) {
    return <Loader />
  }

  if (!isAuthenticated) {
    return (
      <div className="min-h-screen py-8 px-4">
        <div className="max-w-[800px] mx-auto">
          <motion.div
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6 }}
            className="text-center mb-12"
          >
            <h1 className="text-5xl md:text-6xl font-bold mb-4 bg-gradient-to-r from-blue-400 via-purple-400 to-pink-400 bg-clip-text text-transparent">
              Site Analyzer
            </h1>
            <p className="text-lg text-gray-300">
              Анализируйте сайты для создания таргетированной рекламы
            </p>
          </motion.div>
          <LoginForm onLogin={handleLogin} />
        </div>
      </div>
    )
  }

  return (
    <Dashboard
      user={user}
      url={url}
      setUrl={setUrl}
      analyzing={analyzing}
      error={error}
      result={result}
      setResult={setResult}
      onSubmit={handleSubmit}
      onLogout={handleLogout}
    />
  )
}

export default App
