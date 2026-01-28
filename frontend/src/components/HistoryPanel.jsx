import { motion } from 'framer-motion'
import Loader from './Loader'

function HistoryPanel({ history, loading, onAnalysisClick, onLoad }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5 }}
      className="space-y-6"
    >
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-2xl font-bold text-gray-100">История анализов</h2>
        <button
          onClick={onLoad}
          className="px-4 py-2 rounded-lg bg-purple-500/20 border border-purple-500/50 text-purple-300 hover:bg-purple-500/30 transition-all text-sm"
        >
          Обновить
        </button>
      </div>

      {loading ? (
        <div className="flex justify-center py-12">
          <Loader />
        </div>
      ) : history.length === 0 ? (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="text-center py-12 text-gray-400"
        >
          История пуста. Начните анализировать сайты!
        </motion.div>
      ) : (
        <div className="space-y-4">
          {history.map((item, index) => (
            <motion.div
              key={item.id}
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.3, delay: index * 0.1 }}
              onClick={() => onAnalysisClick(item)}
              className="p-5 bg-white/5 backdrop-blur-sm border border-white/10 rounded-xl hover:bg-white/10 hover:border-purple-500/50 cursor-pointer transition-all"
            >
              <div className="flex justify-between items-start mb-3">
                <h3 className="text-lg font-semibold text-blue-400 break-all">{item.url}</h3>
                <span className="text-xs text-gray-400 whitespace-nowrap ml-4">
                  {new Date(item.created_at).toLocaleDateString('ru-RU')}
                </span>
              </div>
              <div className="text-sm text-gray-400">
                <p>Шагов анализа: {item.steps?.length || 0}</p>
                <p>Промежуточных результатов: {item.intermediate_results?.length || 0}</p>
              </div>
            </motion.div>
          ))}
        </div>
      )}
    </motion.div>
  )
}

export default HistoryPanel
