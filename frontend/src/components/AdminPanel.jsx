import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import axios from 'axios'
import { API_BASE_URL } from '../config'

function AdminPanel({ user, onBack }) {
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [editingUser, setEditingUser] = useState(null)
  const [formData, setFormData] = useState({
    email: '',
    username: '',
    password: '',
    role: 'user'
  })

  const loadUsers = async () => {
    setLoading(true)
    try {
      const token = localStorage.getItem('token')
      const response = await axios.get(`${API_BASE_URL}/auth/admin/users`, {
        headers: { Authorization: `Bearer ${token}` }
      })
      setUsers(response.data)
    } catch (err) {
      console.error('Error loading users:', err)
      alert('Ошибка загрузки пользователей')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadUsers()
  }, [])

  const handleCreateUser = async (e) => {
    e.preventDefault()
    try {
      const token = localStorage.getItem('token')
      await axios.post(`${API_BASE_URL}/auth/admin/users`, formData, {
        headers: { Authorization: `Bearer ${token}` }
      })
      setShowCreateForm(false)
      setFormData({ email: '', username: '', password: '', role: 'user' })
      loadUsers()
      alert('Пользователь создан успешно!')
    } catch (err) {
      alert(err.response?.data?.detail || 'Ошибка создания пользователя')
    }
  }

  const handleUpdateUser = async (userId) => {
    try {
      const token = localStorage.getItem('token')
      await axios.put(`${API_BASE_URL}/auth/admin/users/${userId}`, editingUser, {
        headers: { Authorization: `Bearer ${token}` }
      })
      setEditingUser(null)
      loadUsers()
      alert('Пользователь обновлен!')
    } catch (err) {
      alert(err.response?.data?.detail || 'Ошибка обновления пользователя')
    }
  }

  const handleDeleteUser = async (userId, username) => {
    if (!window.confirm(`Удалить пользователя "${username}"?`)) return

    try {
      const token = localStorage.getItem('token')
      await axios.delete(`${API_BASE_URL}/auth/admin/users/${userId}`, {
        headers: { Authorization: `Bearer ${token}` }
      })
      loadUsers()
      alert('Пользователь удален!')
    } catch (err) {
      alert(err.response?.data?.detail || 'Ошибка удаления пользователя')
    }
  }

  const getRoleBadge = (role) => {
    const badges = {
      admin: 'bg-red-500/20 text-red-300 border-red-500/50',
      frontend_dev: 'bg-blue-500/20 text-blue-300 border-blue-500/50',
      user: 'bg-green-500/20 text-green-300 border-green-500/50'
    }
    return badges[role] || badges.user
  }

  const getRoleLabel = (role) => {
    const labels = {
      admin: 'Администратор',
      frontend_dev: 'Frontend Dev',
      user: 'Пользователь'
    }
    return labels[role] || role
  }

  if (loading) {
    return (
      <div className="flex justify-center py-12">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-purple-500"></div>
      </div>
    )
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5 }}
    >
      {/* Header */}
      <div className="flex justify-between items-center mb-8">
        <div>
          <h2 className="text-3xl font-bold text-white mb-2">Управление пользователями</h2>
          <p className="text-gray-400">Создание и управление доступом пользователей</p>
        </div>
        <button
          onClick={onBack}
          className="px-6 py-3 rounded-lg bg-white/10 backdrop-blur-sm border border-white/20 text-white hover:bg-white/20 transition-all"
        >
          ← Назад
        </button>
      </div>

      {/* Create User Button */}
      <motion.button
        whileHover={{ scale: 1.02 }}
        whileTap={{ scale: 0.98 }}
        onClick={() => setShowCreateForm(true)}
        className="w-full mb-8 px-6 py-4 rounded-xl bg-gradient-to-r from-blue-500 to-purple-600 text-white font-semibold hover:from-blue-600 hover:to-purple-700 transition-all"
      >
        + Создать нового пользователя
      </motion.button>

      {/* Create Form */}
      {showCreateForm && (
        <motion.div
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          className="mb-8 p-6 bg-white/5 backdrop-blur-sm border border-white/10 rounded-2xl"
        >
          <h3 className="text-xl font-bold text-white mb-4">Создать пользователя</h3>
          <form onSubmit={handleCreateUser} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-2">Email</label>
              <input
                type="email"
                value={formData.email}
                onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                className="w-full px-4 py-3 rounded-lg bg-white/10 border border-white/20 text-white focus:outline-none focus:ring-2 focus:ring-purple-500"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-2">Имя пользователя</label>
              <input
                type="text"
                value={formData.username}
                onChange={(e) => setFormData({ ...formData, username: e.target.value })}
                className="w-full px-4 py-3 rounded-lg bg-white/10 border border-white/20 text-white focus:outline-none focus:ring-2 focus:ring-purple-500"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-2">Пароль</label>
              <input
                type="password"
                value={formData.password}
                onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                className="w-full px-4 py-3 rounded-lg bg-white/10 border border-white/20 text-white focus:outline-none focus:ring-2 focus:ring-purple-500"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-2">Роль</label>
              <select
                value={formData.role}
                onChange={(e) => setFormData({ ...formData, role: e.target.value })}
                className="w-full px-4 py-3 rounded-lg bg-white/10 border border-white/20 text-white focus:outline-none focus:ring-2 focus:ring-purple-500"
              >
                <option value="user">Пользователь</option>
                <option value="frontend_dev">Frontend-разработчик</option>
                <option value="admin">Администратор</option>
              </select>
            </div>
            <div className="flex gap-4">
              <button
                type="submit"
                className="flex-1 px-6 py-3 rounded-lg bg-gradient-to-r from-blue-500 to-purple-600 text-white font-semibold hover:from-blue-600 hover:to-purple-700 transition-all"
              >
                Создать
              </button>
              <button
                type="button"
                onClick={() => setShowCreateForm(false)}
                className="px-6 py-3 rounded-lg bg-white/10 border border-white/20 text-white hover:bg-white/20 transition-all"
              >
                Отмена
              </button>
            </div>
          </form>
        </motion.div>
      )}

      {/* Users List */}
      <div className="space-y-4">
        <h3 className="text-xl font-bold text-white mb-4">Список пользователей ({users.length})</h3>
        {users.map((u, index) => (
          <motion.div
            key={u.id}
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.3, delay: index * 0.05 }}
            className="p-5 bg-white/5 backdrop-blur-sm border border-white/10 rounded-xl hover:bg-white/10 transition-all"
          >
            {editingUser?.id === u.id ? (
              // Edit Mode
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-2">Email</label>
                  <input
                    type="email"
                    value={editingUser.email || ''}
                    onChange={(e) => setEditingUser({ ...editingUser, email: e.target.value })}
                    className="w-full px-4 py-2 rounded-lg bg-white/10 border border-white/20 text-white focus:outline-none focus:ring-2 focus:ring-purple-500"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-2">Имя пользователя</label>
                  <input
                    type="text"
                    value={editingUser.username || ''}
                    onChange={(e) => setEditingUser({ ...editingUser, username: e.target.value })}
                    className="w-full px-4 py-2 rounded-lg bg-white/10 border border-white/20 text-white focus:outline-none focus:ring-2 focus:ring-purple-500"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-2">Роль</label>
                  <select
                    value={editingUser.role || 'user'}
                    onChange={(e) => setEditingUser({ ...editingUser, role: e.target.value })}
                    className="w-full px-4 py-2 rounded-lg bg-white/10 border border-white/20 text-white focus:outline-none focus:ring-2 focus:ring-purple-500"
                  >
                    <option value="user">Пользователь</option>
                    <option value="frontend_dev">Frontend-разработчик</option>
                    <option value="admin">Администратор</option>
                  </select>
                </div>
                <div className="flex items-center gap-4">
                  <label className="flex items-center gap-2 text-gray-300">
                    <input
                      type="checkbox"
                      checked={editingUser.is_active !== false}
                      onChange={(e) => setEditingUser({ ...editingUser, is_active: e.target.checked })}
                      className="w-5 h-5 rounded"
                    />
                    Активен
                  </label>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => handleUpdateUser(u.id)}
                    className="flex-1 px-4 py-2 rounded-lg bg-green-500/20 border border-green-500/50 text-green-300 hover:bg-green-500/30 transition-all"
                  >
                    Сохранить
                  </button>
                  <button
                    onClick={() => setEditingUser(null)}
                    className="px-4 py-2 rounded-lg bg-white/10 border border-white/20 text-white hover:bg-white/20 transition-all"
                  >
                    Отмена
                  </button>
                </div>
              </div>
            ) : (
              // View Mode
              <div className="flex justify-between items-start">
                <div className="flex-1">
                  <div className="flex items-center gap-3 mb-2">
                    <h4 className="text-lg font-semibold text-white">{u.username}</h4>
                    <span className={`px-3 py-1 rounded-full text-xs font-medium border ${getRoleBadge(u.role)}`}>
                      {getRoleLabel(u.role)}
                    </span>
                    {!u.is_active && (
                      <span className="px-3 py-1 rounded-full text-xs font-medium bg-gray-500/20 text-gray-300 border border-gray-500/50">
                        Неактивен
                      </span>
                    )}
                  </div>
                  <p className="text-gray-400 text-sm mb-1">{u.email}</p>
                  <p className="text-gray-500 text-xs">
                    Создан: {new Date(u.created_at).toLocaleDateString('ru-RU')}
                  </p>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => setEditingUser({
                      id: u.id,
                      email: u.email,
                      username: u.username,
                      role: u.role,
                      is_active: u.is_active
                    })}
                    className="px-4 py-2 rounded-lg bg-blue-500/20 border border-blue-500/50 text-blue-300 hover:bg-blue-500/30 transition-all text-sm"
                  >
                    Редактировать
                  </button>
                  {u.id !== user.id && (
                    <button
                      onClick={() => handleDeleteUser(u.id, u.username)}
                      className="px-4 py-2 rounded-lg bg-red-500/20 border border-red-500/50 text-red-300 hover:bg-red-500/30 transition-all text-sm"
                    >
                      Удалить
                    </button>
                  )}
                </div>
              </div>
            )}
          </motion.div>
        ))}
      </div>
    </motion.div>
  )
}

export default AdminPanel
