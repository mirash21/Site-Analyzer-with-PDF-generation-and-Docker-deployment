import { motion } from 'framer-motion'
import { generatePDFWithPrompt } from '../utils/pdfGenerator'
import { generateDetailedPDFWithPrompt } from '../utils/detailedPdfGenerator'

function ResultCard({ data, delay = 0, url = '', fullAnalysisData = null }) {
  if (!data) return null

  const entries = Object.entries(data)

  const handleExportSimplePDF = async () => {
    const resultElement = document.getElementById('analysis-result')
    if (!resultElement) {
      alert('Не удалось найти элемент для экспорта')
      return
    }

    const defaultFilename = url 
      ? `analysis_${new URL(url).hostname}`
      : `analysis_${new Date().toISOString().slice(0, 10)}`

    const result = await generatePDFWithPrompt(resultElement, defaultFilename)
    
    if (result.success) {
      alert(`PDF файл успешно сохранен: ${result.filename}`)
    } else if (!result.cancelled) {
      alert(`Ошибка при сохранении PDF: ${result.error}`)
    }
  }

  const handleExportDetailedPDF = async () => {
    if (!fullAnalysisData) {
      alert('Нет полных данных для детального отчета')
      return
    }

    const defaultFilename = url 
      ? `detailed_analysis_${new URL(url).hostname}`
      : `detailed_analysis_${new Date().toISOString().slice(0, 10)}`

    const result = await generateDetailedPDFWithPrompt(fullAnalysisData, defaultFilename)
    
    if (result.success) {
      alert(`Детальный PDF отчет успешно сохранен: ${result.filename}`)
    } else if (!result.cancelled) {
      alert(`Ошибка при сохранении отчета: ${result.error}`)
    }
  }

  return (
    <div id="analysis-result" className="space-y-4">
      {/* Кнопки экспорта */}
      <div className="flex justify-end gap-3">
        <motion.button
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          onClick={handleExportSimplePDF}
          className="px-5 py-3 bg-gradient-to-r from-blue-500 to-purple-600 text-white rounded-lg font-semibold hover:from-blue-600 hover:to-purple-700 transition-all flex items-center gap-2 shadow-lg text-sm"
        >
          <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
          Быстрый PDF
        </motion.button>
        
        <motion.button
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          onClick={handleExportDetailedPDF}
          className="px-5 py-3 bg-gradient-to-r from-red-500 to-pink-600 text-white rounded-lg font-semibold hover:from-red-600 hover:to-pink-700 transition-all flex items-center gap-2 shadow-lg text-sm"
        >
          <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
          Детальный PDF
        </motion.button>
      </div>

      {entries.map(([key, value], index) => {
        const isExamples = key.toLowerCase().includes('examples')
        const delayTime = delay + index * 0.15

        if (isExamples && Array.isArray(value)) {
          return (
            <motion.div
              key={key}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4, delay: delayTime }}
              className="bg-gradient-to-br from-purple-500/10 to-blue-500/10 backdrop-blur-sm border border-purple-500/30 rounded-2xl overflow-hidden"
            >
              <div className="p-6">
                <h3 className="text-xl font-bold mb-4 text-purple-300 capitalize">
                  {key.replace(/_/g, ' ')}
                </h3>
                <div className="grid gap-4">
                  {value.map((item, itemIndex) => (
                    <motion.div
                      key={itemIndex}
                      initial={{ opacity: 0, x: -20 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ duration: 0.3, delay: delayTime + 0.2 + itemIndex * 0.1 }}
                      className="p-4 bg-white/5 rounded-xl border border-white/10 hover:bg-white/10 transition-all"
                    >
                      <p className="text-gray-200 whitespace-pre-wrap">{item}</p>
                    </motion.div>
                  ))}
                </div>
              </div>
            </motion.div>
          )
        }

        return (
          <motion.div
            key={key}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, delay: delayTime }}
            className="bg-gradient-to-br from-blue-500/10 to-purple-500/10 backdrop-blur-sm border border-blue-500/30 rounded-2xl overflow-hidden"
          >
            <div className="p-6">
              <h3 className="text-xl font-bold mb-3 text-blue-300 capitalize">
                {key.replace(/_/g, ' ')}
              </h3>
              <p className="text-gray-200 whitespace-pre-wrap">{value}</p>
            </div>
          </motion.div>
        )
      })}
    </div>
  )
}

export default ResultCard
