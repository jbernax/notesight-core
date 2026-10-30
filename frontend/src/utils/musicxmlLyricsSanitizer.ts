/**
 * MusicXML Lyrics Anti-Collision & Multi-Word Sanitizer
 *
 * Scanned sheet music or OCR-extracted lyrics can occasionally bundle multiple words
 * or entire phrases into a single <note><lyric><text> phrase (e.g., "To heal the wounds").
 * In standard notation engraving (OSMD/VexFlow), this causes severe horizontal collisions
 * because multiple words are rendered in the space of a single short note.
 *
 * This sanitizer:
 * 1. Identifies <note><lyric><text> nodes containing multiple whitespace-separated words.
 * 2. Splits them into individual word tokens.
 * 3. Keeps the first word on the current note.
 * 4. Distributes subsequent words onto subsequent notes (notes without lyrics) in the part.
 * 5. Guarantees no multi-word sentences remain jammed under individual notes.
 */

export function sanitizeMusicXmlLyrics(xmlStr: string): string {
  if (!xmlStr || typeof DOMParser === 'undefined' || typeof XMLSerializer === 'undefined') {
    return xmlStr
  }

  const needsLyricsSanitize = xmlStr.includes('<lyric')
  const needsRestSanitize = xmlStr.includes('measure="yes"') || xmlStr.includes('<rest') || xmlStr.includes('<note')

  if (!needsLyricsSanitize && !needsRestSanitize) {
    return xmlStr
  }

  try {
    const parser = new DOMParser()
    const doc = parser.parseFromString(xmlStr, 'application/xml')

    const parserError = doc.querySelector('parsererror')
    if (parserError) {
      return xmlStr
    }

    const parts = Array.from(doc.querySelectorAll('part'))
    if (parts.length === 0) {
      return xmlStr
    }

    let modified = false

    // Discover global divisions, time signature, and key from the score
    let defaultDivisions = '8'
    let defaultBeats = '4'
    let defaultBeatType = '4'
    let defaultKey: Element | null = null

    for (const part of parts) {
      for (const measure of Array.from(part.querySelectorAll('measure'))) {
        const attr = measure.querySelector('attributes')
        if (attr) {
          const div = attr.querySelector('divisions')
          if (div && div.textContent && defaultDivisions === '8') {
            defaultDivisions = div.textContent.trim()
          }
          const b = attr.querySelector('time > beats')
          const bt = attr.querySelector('time > beat-type')
          if (b && bt && b.textContent && bt.textContent && defaultBeats === '4' && defaultBeatType === '4') {
            defaultBeats = b.textContent.trim()
            defaultBeatType = bt.textContent.trim()
          }
          const k = attr.querySelector('key')
          if (k && !defaultKey) {
            defaultKey = k.cloneNode(true) as Element
          }
        }
        if (defaultDivisions !== '8' && (defaultBeats !== '4' || defaultBeatType !== '4') && defaultKey) break
      }
    }

    parts.forEach((part) => {
      const pendingWords: string[] = []
      const measures = Array.from(part.querySelectorAll('measure'))
      if (measures.length === 0) return

      // Ensure measure 1 has attributes with divisions and time
      let firstMeasureAttr = measures[0].querySelector('attributes')
      if (!firstMeasureAttr) {
        firstMeasureAttr = doc.createElement('attributes')
        const divElem = doc.createElement('divisions')
        divElem.textContent = defaultDivisions
        firstMeasureAttr.appendChild(divElem)

        const timeElem = doc.createElement('time')
        const bElem = doc.createElement('beats')
        bElem.textContent = defaultBeats
        const btElem = doc.createElement('beat-type')
        btElem.textContent = defaultBeatType
        timeElem.appendChild(bElem)
        timeElem.appendChild(btElem)
        firstMeasureAttr.appendChild(timeElem)

        if (defaultKey) {
          firstMeasureAttr.appendChild(defaultKey.cloneNode(true))
        }

        measures[0].insertBefore(firstMeasureAttr, measures[0].firstChild)
        modified = true
      } else {
        if (!firstMeasureAttr.querySelector('divisions')) {
          const divElem = doc.createElement('divisions')
          divElem.textContent = defaultDivisions
          firstMeasureAttr.insertBefore(divElem, firstMeasureAttr.firstChild)
          modified = true
        }
        if (!firstMeasureAttr.querySelector('time')) {
          const timeElem = doc.createElement('time')
          const bElem = doc.createElement('beats')
          bElem.textContent = defaultBeats
          const btElem = doc.createElement('beat-type')
          btElem.textContent = defaultBeatType
          timeElem.appendChild(bElem)
          timeElem.appendChild(btElem)
          firstMeasureAttr.appendChild(timeElem)
          modified = true
        }
      }

      let curDiv = parseInt(defaultDivisions, 10) || 8
      let curBeats = parseInt(defaultBeats, 10) || 4
      let curBeatType = parseInt(defaultBeatType, 10) || 4

      measures.forEach((measure) => {
        const attr = measure.querySelector('attributes')
        if (attr) {
          const div = attr.querySelector('divisions')
          if (div && div.textContent) curDiv = parseInt(div.textContent.trim(), 10) || curDiv
          const b = attr.querySelector('time > beats')
          const bt = attr.querySelector('time > beat-type')
          if (b && bt && b.textContent && bt.textContent) {
            curBeats = parseInt(b.textContent.trim(), 10) || curBeats
            curBeatType = parseInt(bt.textContent.trim(), 10) || curBeatType
          }
        }

        const fullMeasureDur = Math.max(1, Math.round(curDiv * 4 * (curBeats / curBeatType)))

        // 1. Sanitize measure rests and durations to prevent VexFlow / OSMD crash: "duration is not valid: u"
        const allNotes = Array.from(measure.querySelectorAll('note'))
        allNotes.forEach((note) => {
          const rest = note.querySelector('rest')
          const dur = note.querySelector('duration')
          const isMeasureRest = rest && rest.getAttribute('measure') === 'yes'
          const isGrace = note.querySelector('grace') !== null

          const durVal = dur?.textContent ? parseInt(dur.textContent.trim(), 10) : NaN
          const hasValidDur = !isNaN(durVal) && durVal > 0

          if (isMeasureRest) {
            if (!hasValidDur) {
              if (!dur) {
                const newDur = doc.createElement('duration')
                newDur.textContent = String(fullMeasureDur)
                note.appendChild(newDur)
              } else {
                dur.textContent = String(fullMeasureDur)
              }
              modified = true
            }
            if (!note.querySelector('type')) {
              const typeElem = doc.createElement('type')
              typeElem.textContent = 'whole'
              note.appendChild(typeElem)
              modified = true
            }
            if (!note.querySelector('voice')) {
              const vElem = doc.createElement('voice')
              vElem.textContent = '1'
              note.appendChild(vElem)
              modified = true
            }
          } else if (!isGrace && !hasValidDur) {
            if (!dur) {
              const newDur = doc.createElement('duration')
              newDur.textContent = String(curDiv)
              note.appendChild(newDur)
            } else {
              dur.textContent = String(curDiv)
            }
            if (!note.querySelector('voice')) {
              const vElem = doc.createElement('voice')
              vElem.textContent = '1'
              note.appendChild(vElem)
            }
            modified = true
          }
        })

        // 2. Lyrics anti-collision splitting
        if (needsLyricsSanitize) {
          const notes = allNotes.filter((note) => {
            const isRest = note.querySelector('rest') !== null
            const isChord = note.querySelector('chord') !== null
            const isGrace = note.querySelector('grace') !== null
            return !isRest && !isChord && !isGrace
          })

          notes.forEach((note) => {
            const lyric = note.querySelector('lyric')
            if (lyric) {
              const textElem = lyric.querySelector('text')
              if (textElem && textElem.textContent) {
                const trimmed = textElem.textContent.trim()
                const words = trimmed.split(/\s+/).filter(Boolean)
                if (words.length > 1) {
                  textElem.textContent = words[0]
                  for (let i = 1; i < words.length; i++) {
                    pendingWords.push(words[i])
                  }
                  modified = true
                }
              }
            } else if (pendingWords.length > 0) {
              const word = pendingWords.shift()!
              const newLyric = doc.createElement('lyric')
              newLyric.setAttribute('number', '1')
              const sylElem = doc.createElement('syllabic')
              sylElem.textContent = 'single'
              newLyric.appendChild(sylElem)
              const textElem = doc.createElement('text')
              textElem.textContent = word
              newLyric.appendChild(textElem)
              note.appendChild(newLyric)
              modified = true
            }
          })
        }
      })
    })

    if (!modified) {
      return xmlStr
    }

    const serializer = new XMLSerializer()
    return serializer.serializeToString(doc)
  } catch {
    return xmlStr
  }
}
