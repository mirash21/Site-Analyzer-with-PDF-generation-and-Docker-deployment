import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import Loader from './Loader'
import ResultCard from './ResultCard'
import RichText from './RichText'
import HistoryPanel from './HistoryPanel'
import AdminPanel from './AdminPanel'
import { API_BASE_URL } from '../config'

function Dashboard({ user, url, setUrl, analyzing, error, result, setResult, onSubmit, onLogout }) {
  const [showHistory, setShowHistory] = useState(false)
  const [showAdmin, setShowAdmin] = useState(false)
  const [history, setHistory] = useState([])
  const [loadingHistory, setLoadingHistory] = useState(false)

  const loadHistory = async () => {
    setLoadingHistory(true)
    try {
      const token = localStorage.getItem('token')
      const response = await fetch(`${API_BASE_URL}/history/analyses`, {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      })
      const data = await response.json()
      console.log('Загружена история:', data)
      setHistory(data)
    } catch (err) {
      console.error('Error loading history:', err)
    } finally {
      setLoadingHistory(false)
    }
  }

  useEffect(() => {
    if (showHistory) {
      loadHistory()
    }
  }, [showHistory])

  const handleHistoryClick = (analysisData) => {
    console.log('Выбран анализ из истории:', analysisData)
    setResult(analysisData)
    setUrl(analysisData.url)
    setShowHistory(false)
  }

  const isAdmin = user?.role === 'admin' || user?.role === 'frontend_dev'

  return (
    <div className="min-h-screen py-8 px-4 print-wide">
      <div className="max-w-[800px] mx-auto print-wide">
        {/* Header with user info */}
        <motion.div
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
          className="flex justify-between items-center mb-12 no-print"
        >
          <div>
            <h1 className="text-5xl md:text-6xl font-bold mb-2 bg-gradient-to-r from-blue-400 via-purple-400 to-pink-400 bg-clip-text text-transparent">
              Site Analyzer
            </h1>
            <p className="text-lg text-gray-300">
              Добро пожаловать, {user?.username}!
              {user?.role === 'admin' && (
                <span className="ml-2 px-2 py-1 rounded bg-red-500/20 text-red-300 text-xs">Администратор</span>
              )}
              {user?.role === 'frontend_dev' && (
                <span className="ml-2 px-2 py-1 rounded bg-blue-500/20 text-blue-300 text-xs">Frontend Dev</span>
              )}
            </p>
          </div>
          <button
            onClick={onLogout}
            className="px-4 py-2 rounded-lg bg-white/10 backdrop-blur-sm border border-white/20 text-white hover:bg-white/20 transition-all"
          >
            Выйти
          </button>
        </motion.div>

        {/* Admin Button (only for admins) */}
        {isAdmin && (
          <motion.button
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            onClick={() => setShowAdmin(!showAdmin)}
            className={`no-print w-full mb-4 px-6 py-3 rounded-lg text-white font-semibold transition-all ${
              showAdmin
                ? 'bg-red-500/20 border border-red-500/50 text-red-300'
                : 'bg-gradient-to-r from-red-500 to-pink-600'
            }`}
          >
            {showAdmin ? '← Вернуться к анализу' : '⚙️ Панель администратора'}
          </motion.button>
        )}

        {showAdmin ? (
          <AdminPanel user={user} onBack={() => setShowAdmin(false)} />
        ) : (
          <>
            {/* Toggle History Button */}
            <motion.button
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              onClick={() => setShowHistory(!showHistory)}
              className="no-print w-full mb-6 px-6 py-3 rounded-lg bg-white/5 backdrop-blur-sm border border-white/10 text-white hover:bg-white/10 transition-all"
            >
              {showHistory ? '← Вернуться к анализу' : '📜 История анализов'}
            </motion.button>

            {showHistory ? (
              <HistoryPanel
                history={history}
                loading={loadingHistory}
                onAnalysisClick={handleHistoryClick}
                onLoad={loadHistory}
              />
            ) : (
              <>
                {/* Form */}
                <motion.form
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.6, delay: 0.2 }}
                  onSubmit={onSubmit}
                  className="mb-12 no-print"
                >
              <div className="flex flex-col sm:flex-row gap-4">
                <input
                  type="url"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="Введите URL сайта..."
                  className="flex-1 px-6 py-4 rounded-xl bg-white/10 backdrop-blur-sm border border-white/20 text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent transition-all"
                />
                <button
                  type="submit"
                  disabled={analyzing}
                  className="px-8 py-4 rounded-xl bg-gradient-to-r from-blue-500 to-purple-600 text-white font-semibold hover:from-blue-600 hover:to-purple-700 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:ring-offset-2 focus:ring-offset-slate-900 transition-all disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap"
                >
                  {analyzing ? 'Анализируем...' : 'Отправить'}
                </button>
              </div>
            </motion.form>

            {/* Loader */}
            {analyzing && (
              <div className="no-print">
                <Loader />
              </div>
            )}

            {/* Error */}
            {error && (
              <motion.div
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                className="no-print mb-8 p-6 bg-red-500/20 backdrop-blur-sm border border-red-500/50 rounded-xl text-red-200"
              >
                <p className="font-semibold mb-2">Ошибка</p>
                <p>{error}</p>
              </motion.div>
            )}

            {/* Results */}
            {result && (
              <motion.div
                id="report-root"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.5 }}
                className="space-y-6"
              >
                {/* URL */}
                <motion.div
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.5, delay: 0.1 }}
                  className="p-4 bg-white/5 backdrop-blur-sm border border-white/10 rounded-xl"
                >
                  <p className="text-sm text-gray-400 mb-1">Анализируемый сайт</p>
                  <p className="text-lg font-medium text-blue-400 break-all">{result.url}</p>
                </motion.div>

                {/* Итоговый анализ идёт первым: это то, ради чего открывают отчёт. */}
                {result.final_analysis && (
                  <div>
                    <h2 className="text-2xl font-bold mb-4 text-gray-100">Итоговый анализ</h2>
                    <ResultCard
                      data={result.final_analysis}
                      delay={0.7}
                      url={result.url}
                      fullAnalysisData={result}
                      analysisId={result.id}
                    />
                  </div>
                )}

                {/* Служебные секции свёрнуты: ~30 KB markdown промежуточных
                    ответов делали отчёт нечитаемым. В печать кнопка экспорта
                    разворачивает их автоматически. */}
                {(result.steps?.length > 0 || result.intermediate_results?.length > 0) && (
                  <details className="analysis-card p-5 bg-white/5 backdrop-blur-sm border border-white/10 rounded-xl">
                    <summary className="cursor-pointer text-lg font-semibold text-gray-100">
                      Как получен результат: шаги и промежуточные ответы
                    </summary>

                    {result.steps?.length > 0 && (
                      <div className="mt-5">
                        <h3 className="text-base font-semibold text-purple-300 mb-3">Шаги анализа</h3>
                        <ol className="space-y-2">
                          {result.steps.map((step, index) => (
                            <li key={index} className="report-li text-gray-200">
                              <span className="text-purple-400 font-semibold">{index + 1}. </span>
                              <RichText>{step}</RichText>
                            </li>
                          ))}
                        </ol>
                      </div>
                    )}

                    {result.intermediate_results?.length > 0 && (
                      <div className="mt-6 space-y-4">
                        <h3 className="text-base font-semibold text-purple-300 mb-3">
                          Промежуточные результаты
                        </h3>
                        {result.intermediate_results.map((item, index) => (
                          <div
                            key={index}
                            className="analysis-card p-4 rounded-xl border border-white/10 bg-white/5"
                          >
                            <p className="text-sm text-purple-400 font-semibold mb-1">
                              Шаг {item.step_number}
                            </p>
                            {item.step && (
                              <p className="text-sm text-gray-400 mb-3">{item.step}</p>
                            )}
                            <RichText>{item.result}</RichText>
                          </div>
                        ))}
                      </div>
                    )}
                  </details>
                )}
              </motion.div>
            )}
              </>
            )}
          </>
        )}
      </div>
    </div>
  )
}

export default Dashboard
