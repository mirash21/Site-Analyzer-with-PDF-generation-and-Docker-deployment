import { API_BASE_URL } from '../config'

// Скачивание PDF, собранного на сервере. Раньше PDF склеивался из одного
// canvas-скриншота прямо в браузере: длинные отчёты обрезались по лимиту
// canvas, а строки разрезались пополам на границе страницы.
export async function downloadAnalysisPDF(analysisId, siteUrl = '') {
  const token = localStorage.getItem('token')
  const response = await fetch(`${API_BASE_URL}/history/analysis/${analysisId}/pdf`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })

  if (!response.ok) {
    let detail = `ошибка ${response.status}`
    try {
      const payload = await response.json()
      if (payload?.detail) detail = payload.detail
    } catch (error) {
      // Ответ не JSON (например, nginx отдал свою страницу) — оставляем код статуса.
    }
    throw new Error(detail)
  }

  let hostname = 'report'
  try {
    hostname = new URL(siteUrl).hostname || 'report'
  } catch (error) {
    // URL мог быть пустым или без схемы — имя файла не критично.
  }
  const date = new Date().toISOString().slice(0, 10)
  const filename = `analysis_${hostname}_${date}.pdf`

  const href = URL.createObjectURL(await response.blob())
  const link = document.createElement('a')
  link.href = href
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  // Отпускаем URL после того, как браузер успел забрать blob.
  setTimeout(() => URL.revokeObjectURL(href), 2000)

  return filename
}
