/**
 * Utility to synchronize and update the score title across MusicXML structure.
 * Updates <work-title>, <movement-title>, and title <credit-words> elements.
 */

export function updateMusicXmlTitle(musicXml: string, newTitle: string): string {
  const trimmedTitle = newTitle.trim()
  if (!trimmedTitle || !musicXml) {
    return musicXml
  }

  try {
    if (typeof window !== 'undefined' && window.DOMParser) {
      const parser = new DOMParser()
      const doc = parser.parseFromString(musicXml, 'application/xml')
      
      const parserError = doc.querySelector('parsererror')
      if (!parserError) {
        const root = doc.documentElement

        // 1. Update or create <work><work-title>
        let work = root.querySelector('work')
        if (!work) {
          work = doc.createElement('work')
          // Insert as first child of score-partwise / score-timewise
          root.insertBefore(work, root.firstChild)
        }
        let workTitle = work.querySelector('work-title')
        if (!workTitle) {
          workTitle = doc.createElement('work-title')
          work.appendChild(workTitle)
        }
        workTitle.textContent = trimmedTitle

        // 2. Update <movement-title> if it exists
        const movementTitle = root.querySelector('movement-title')
        if (movementTitle) {
          movementTitle.textContent = trimmedTitle
        }

        // 3. Update <credit> elements with <credit-type>title</credit-type>
        const credits = root.querySelectorAll('credit')
        credits.forEach((credit) => {
          const typeEl = credit.querySelector('credit-type')
          if (typeEl && typeEl.textContent?.trim().toLowerCase() === 'title') {
            const wordsEl = credit.querySelector('credit-words')
            if (wordsEl) {
              wordsEl.textContent = trimmedTitle
            }
          }
        })

        const serializer = new XMLSerializer()
        return serializer.serializeToString(doc)
      }
    }
  } catch (err) {
    console.warn('DOMParser failed in updateMusicXmlTitle, falling back to regex:', err)
  }

  // Robust Regex Fallback
  let updated = musicXml
  if (/<work-title>[^<]*<\/work-title>/i.test(updated)) {
    updated = updated.replace(/<work-title>[^<]*<\/work-title>/gi, `<work-title>${escapeXml(trimmedTitle)}</work-title>`)
  } else if (/<work>/i.test(updated)) {
    updated = updated.replace(/<work>/i, `<work><work-title>${escapeXml(trimmedTitle)}</work-title>`)
  }

  if (/<movement-title>[^<]*<\/movement-title>/i.test(updated)) {
    updated = updated.replace(/<movement-title>[^<]*<\/movement-title>/gi, `<movement-title>${escapeXml(trimmedTitle)}</movement-title>`)
  }

  // Regex fallback for credit-type title
  updated = updated.replace(
    /(<credit[^>]*>[\s\S]*?<credit-type>[^<]*title[^<]*<\/credit-type>[\s\S]*?<credit-words[^>]*>)([^<]*)(<\/credit-words>)/gi,
    `$1${escapeXml(trimmedTitle)}$3`
  )

  return updated
}

function escapeXml(unsafe: string): string {
  return unsafe
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;')
}
