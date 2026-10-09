"""Base SQLite locale : chaque bip y est écrit AVANT tout envoi réseau.
Ainsi rien n'est perdu si le Wi-Fi tombe ou si le serveur est éteint."""
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone


class Stockage:
    def __init__(self, chemin: str):
        # check_same_thread=False + verrou : la lecture et la synchro tournent dans deux threads
        self.conn = sqlite3.connect(chemin, check_same_thread=False)
        self.verrou = threading.Lock()
        with self.verrou:
            self.conn.execute("PRAGMA journal_mode=WAL")      # résiste mieux aux coupures de courant
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS pointages (
                    uuid      TEXT PRIMARY KEY,
                    nfc_uid   TEXT NOT NULL,
                    timestamp TEXT NOT NULL,            -- ISO 8601 en UTC
                    synced    INTEGER NOT NULL DEFAULT 0
                )""")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_synced ON pointages(synced)")
            # Copie locale des cartes associées à un étudiant (envoyée par le serveur à chaque synchro)
            self.conn.execute("CREATE TABLE IF NOT EXISTS cartes_connues (nfc_uid TEXT PRIMARY KEY)")
            self.conn.execute("CREATE TABLE IF NOT EXISTS infos (cle TEXT PRIMARY KEY, valeur TEXT)")
            self.conn.commit()
            self.liste_recue = self.conn.execute(
                "SELECT 1 FROM infos WHERE cle = 'cartes_recues'").fetchone() is not None
            self.cartes = {u for (u,) in self.conn.execute("SELECT nfc_uid FROM cartes_connues")}

    def ajouter(self, nfc_uid: str) -> dict:
        """Enregistre un bip (UUID v4 + heure UTC) avec synced = 0."""
        pointage = {
            "uuid": str(uuid.uuid4()),
            "nfc_uid": nfc_uid,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        with self.verrou:
            self.conn.execute("INSERT INTO pointages (uuid, nfc_uid, timestamp) VALUES (?, ?, ?)",
                              (pointage["uuid"], pointage["nfc_uid"], pointage["timestamp"]))
            self.conn.commit()
        return pointage

    def remplacer_cartes(self, uids: list):
        """Remplace la liste locale des cartes connues (seulement si elle a changé)."""
        nouvelles = set(uids)
        if self.liste_recue and nouvelles == self.cartes:
            return
        with self.verrou:
            self.conn.execute("DELETE FROM cartes_connues")
            self.conn.executemany("INSERT INTO cartes_connues (nfc_uid) VALUES (?)", [(u,) for u in nouvelles])
            self.conn.execute("INSERT OR REPLACE INTO infos (cle, valeur) VALUES ('cartes_recues', '1')")
            self.conn.commit()
        self.cartes, self.liste_recue = nouvelles, True

    def carte_connue(self, nfc_uid: str):
        """True / False, ou None si le boîtier n'a encore jamais reçu la liste du serveur
        (premier démarrage sans réseau) : on ne peut pas savoir, on ne bloque pas."""
        if not self.liste_recue:
            return None
        return nfc_uid in self.cartes

    def a_envoyer(self, limite: int) -> list:
        with self.verrou:
            lignes = self.conn.execute(
                "SELECT uuid, nfc_uid, timestamp FROM pointages WHERE synced = 0 ORDER BY timestamp LIMIT ?",
                (limite,)).fetchall()
        return [{"uuid": u, "nfc_uid": n, "timestamp": t} for u, n, t in lignes]

    def marquer_envoyes(self, uuids: list):
        if not uuids:
            return
        with self.verrou:
            self.conn.executemany("UPDATE pointages SET synced = 1 WHERE uuid = ?", [(u,) for u in uuids])
            self.conn.commit()

    def nb_en_attente(self) -> int:
        with self.verrou:
            return self.conn.execute("SELECT COUNT(*) FROM pointages WHERE synced = 0").fetchone()[0]

    def nettoyer(self, jours: int):
        """Supprime les pointages déjà envoyés depuis plus de `jours` jours (RGPD + place)."""
        limite = (datetime.now(timezone.utc) - timedelta(days=jours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self.verrou:
            self.conn.execute("DELETE FROM pointages WHERE synced = 1 AND timestamp < ?", (limite,))
            self.conn.commit()
