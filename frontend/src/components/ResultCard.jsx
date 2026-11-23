import { motion } from 'framer-motion'
import RichText, { KeywordList } from './RichText'
import { labelFor, formatDate } from '../utils/labels'
import { downloadAnalysisPDF } from '../utils/pdfDownload'

// Список фраз — не текст: его копируют в рекламный кабинет целиком.
const KEYWORD_KEYS = ['keyword_seeds', 'negative_keywords']

// Итоговый анализ: ключи JSON-схемы превращаются в разделы отчёта.
// Значение может быть строкой с markdown, списком строк, списком объектов или
// таблицей {columns, rows} — всё это рисует RichText, поэтому ни «[object
// Object]», ни падения «Objects are not valid as a React child» здесь уже нет.
function ResultCard({ data, delay = 0, url = '', fullAnalysisData = null, analysisId = null }) {
  if (!data) return null

  const entries = Object.entries(data)

  const handlePrint = () => {
    // На экране служебные секции свёрнуты, в отчёте они обязаны быть.
    const collapsed = Array.from(
      document.querySelectorAll('#report-root details:not([open])')
    )
    collapsed.forEach((details) => {
      details.open = true
    })
    const restore = () => {
      collapsed.forEach((details) => {
        details.open = false
      })
      window.removeEventListener('afterprint', restore)
    }
    window.addEventListener('afterprint', restore)
    window.print()
  }

  const handleDetailedPDF = async () => {
    const id = analysisId || fullAnalysisData?.id
    if (!id) {
      alert('Отчёт ещё не сохранён в истории — скачивание недоступно. Используйте печать.')
      return
    }
    try {
      await downloadAnalysisPDF(id, fullAnalysisData?.url || url)
    } catch (error) {
      alert(`Не удалось скачать PDF: ${error.message}`)
    }
  }

  return (
    <div className="space-y-4">
      {/* Экспорт. В печать не попадает. */}
      <div className="flex justify-end gap-3 no-print">
        <motion.button
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          onClick={handleDetailedPDF}
          className="px-5 py-3 bg-gradient-to-r from-red-500 to-pink-600 text-white rounded-lg font-semibold hover:from-red-600 hover:to-pink-700 transition-all flex items-center gap-2 shadow-lg text-sm"
        >
          <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
          </svg>
          Скачать PDF
        </motion.button>

        <motion.button
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          onClick={handlePrint}
          className="px-5 py-3 bg-gradient-to-r from-blue-500 to-purple-600 text-white rounded-lg font-semibold hover:from-blue-600 hover:to-purple-700 transition-all flex items-center gap-2 shadow-lg text-sm"
        >
          <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 17h2a2 2 0 002-2v-4a2 2 0 00-2-2H5a2 2 0 00-2 2v4a2 2 0 002 2h2m2 4h6a2 2 0 002-2v-4a2 2 0 00-2-2H9a2 2 0 00-2 2v4a2 2 0 002 2zm8-12V5a2 2 0 00-2-2H9a2 2 0 00-2 2v4h10z" />
          </svg>
          Печать / PDF
        </motion.button>
      </div>

      {entries.map(([key, value], index) => {
        const delayTime = delay + index * 0.15

        return (
          <motion.div
            key={key}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, delay: delayTime }}
            className="analysis-card bg-gradient-to-br from-blue-500/10 to-purple-500/10 backdrop-blur-sm border border-blue-500/30 rounded-2xl overflow-hidden"
          >
            <div className="p-6">
              <h3 className="text-xl font-bold mb-3 text-blue-300">
                {labelFor(key)}
              </h3>
              {KEYWORD_KEYS.includes(key) && Array.isArray(value)
                ? <KeywordList items={value} />
                : <RichText>{value}</RichText>}
            </div>
          </motion.div>
        )
      })}

      {/* Шапка печатной версии: на экране она не нужна, в PDF обязана быть. */}
      <div className="only-print print-header">
        <p className="print-title">Отчёт об анализе сайта</p>
        <p className="print-url">{url || fullAnalysisData?.url || 'не указан'}</p>
        {fullAnalysisData?.created_at && (
          <p className="print-date">Дата анализа: {formatDate(fullAnalysisData.created_at)}</p>
        )}
      </div>
    </div>
  )
}

export default ResultCard
