/**
 * NoteSight Mobile Offline Cache Service
 * Persists scores and audio resources using IndexedDB for seamless offline rehearsal.
 */

export interface OfflineScore {
  id: string;
  title: string;
  composer?: string;
  xml: string;
  partCount?: number;
  savedAt: number;
  measureCount?: number;
}

const DB_NAME = 'notesight_offline_db';
const DB_VERSION = 1;
const STORE_NAME = 'scores';

let dbPromise: Promise<IDBDatabase> | null = null;

function getDb(): Promise<IDBDatabase> {
  if (dbPromise) return dbPromise;

  dbPromise = new Promise((resolve, reject) => {
    if (typeof window === 'undefined' || !window.indexedDB) {
      return reject(new Error('IndexedDB is not supported in this environment'));
    }

    const request = window.indexedDB.open(DB_NAME, DB_VERSION);

    request.onupgradeneeded = (event) => {
      const db = (event.target as IDBOpenDBRequest).result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        const store = db.createObjectStore(STORE_NAME, { keyPath: 'id' });
        store.createIndex('savedAt', 'savedAt', { unique: false });
        store.createIndex('title', 'title', { unique: false });
      }
    };

    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });

  return dbPromise;
}

export async function saveScoreOffline(score: {
  id: string;
  title: string;
  composer?: string;
  xml: string;
  partCount?: number;
  measureCount?: number;
}): Promise<void> {
  const db = await getDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite');
    const store = tx.objectStore(STORE_NAME);

    const record: OfflineScore = {
      ...score,
      savedAt: Date.now(),
    };

    const request = store.put(record);
    request.onsuccess = () => resolve();
    request.onerror = () => reject(request.error);
  });
}

export async function getOfflineScore(id: string): Promise<OfflineScore | null> {
  const db = await getDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readonly');
    const store = tx.objectStore(STORE_NAME);
    const request = store.get(id);

    request.onsuccess = () => resolve(request.result || null);
    request.onerror = () => reject(request.error);
  });
}

export async function listOfflineScores(): Promise<OfflineScore[]> {
  const db = await getDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readonly');
    const store = tx.objectStore(STORE_NAME);
    const index = store.index('savedAt');
    const request = index.getAll();

    request.onsuccess = () => {
      // Sort newest first
      const results = (request.result as OfflineScore[]).reverse();
      resolve(results);
    };
    request.onerror = () => reject(request.error);
  });
}

export async function deleteOfflineScore(id: string): Promise<void> {
  const db = await getDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite');
    const store = tx.objectStore(STORE_NAME);
    const request = store.delete(id);

    request.onsuccess = () => resolve();
    request.onerror = () => reject(request.error);
  });
}

export async function isScoreOffline(id: string): Promise<boolean> {
  try {
    const score = await getOfflineScore(id);
    return score !== null;
  } catch {
    return false;
  }
}
