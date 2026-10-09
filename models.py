from sqlalchemy import Boolean, Column, String, Integer, DateTime, ForeignKey, Table, inspect, text
from sqlalchemy.orm import relationship
from database import Base

# Convention horaire : toutes les dates stockées en base (séances ET pointages)
# sont en heure locale de Paris, sans fuseau ("naive"). Le boîtier envoie de l'UTC,
# la conversion est faite à la réception dans main.py.

# Table de liaison pour le Many-to-Many (placée en haut)
etudiant_groupe_association = Table(
    'etudiant_groupe_association',
    Base.metadata,
    Column('etudiant_id', Integer, ForeignKey('etudiants.id', ondelete="CASCADE"), primary_key=True),
    Column('groupe_id', Integer, ForeignKey('groupes.id', ondelete="CASCADE"), primary_key=True)
)

class GroupeDB(Base):
    __tablename__ = "groupes"
    id = Column(Integer, primary_key=True, index=True)
    nom_groupe = Column(String(16), unique=True, nullable=False)

    etudiants = relationship("EtudiantDB", secondary=etudiant_groupe_association, back_populates="groupes")

class SalleDB(Base):
    __tablename__ = "salles"
    id = Column(Integer, primary_key=True, index=True)
    nom_salle = Column(String(32), unique=True, nullable=False)

class EnseignementDB(Base):
    __tablename__ = "enseignements"
    id = Column(Integer, primary_key=True, index=True)
    code_cours = Column(String(32), unique=True, nullable=False)
    libelle = Column(String(128), nullable=False)

class ProfesseurDB(Base):
    __tablename__ = "professeurs"
    id = Column(Integer, primary_key=True, index=True)
    nom = Column(String(64), nullable=False)
    prenom = Column(String(64), nullable=False)
    # Compte de connexion (facultatif) : le prof voit et valide ses propres cours
    identifiant = Column(String(64), unique=True, nullable=True)
    mot_de_passe = Column(String(255), nullable=True)          # haché (services/comptes.py)

class EtudiantDB(Base):
    __tablename__ = "etudiants"
    id = Column(Integer, primary_key=True, index=True)
    numero_etudiant = Column(String(32), unique=True, index=True, nullable=False)
    nom = Column(String(64), nullable=False)
    prenom = Column(String(64), nullable=False)

    # lazy="selectin" : pour une liste d'étudiants, groupes et cartes sont chargés en une
    # requête chacun, au lieu de 2 requêtes par étudiant (pages beaucoup plus rapides)
    groupes = relationship("GroupeDB", secondary=etudiant_groupe_association, back_populates="etudiants",
                           lazy="selectin")
    carte = relationship("CarteDB", back_populates="etudiant", uselist=False, cascade="all, delete-orphan",
                         lazy="selectin")

class CarteDB(Base):
    __tablename__ = "cartes"
    nfc_uid = Column(String(64), primary_key=True, index=True)
    id_etudiant = Column(Integer, ForeignKey("etudiants.id"), unique=True, nullable=False)

    etudiant = relationship("EtudiantDB", back_populates="carte")

class BoitierDB(Base):
    """Un Raspberry Pi. Chaque prof a son boîtier attitré (livrable p1) ;
    la salle sert de solution de repli si le prof n'est pas reconnu dans l'EDT."""
    __tablename__ = "boitiers"
    device_id = Column(String(32), primary_key=True, index=True)
    token = Column(String(64), nullable=False)
    id_prof = Column(Integer, ForeignKey("professeurs.id", ondelete="SET NULL"), nullable=True)
    id_salle = Column(Integer, ForeignKey("salles.id", ondelete="SET NULL"), nullable=True)
    derniere_synchro = Column(DateTime, nullable=True)
    # Boîtier "SAE" : un bip est rattaché à la séance de SAE du groupe de l'étudiant
    # à cette heure-là, quels que soient la salle et le professeur
    mode_sae = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    # Boîtier d'accueil : le seul proposé pour enregistrer les cartes ("Scanner la carte")
    accueil = Column(Boolean, nullable=False, default=False, server_default=text("false"))

    professeur = relationship("ProfesseurDB")
    salle = relationship("SalleDB")

class PointageDB(Base):
    __tablename__ = "pointages"
    uuid = Column(String(36), primary_key=True, index=True)
    nfc_uid = Column(String(64), nullable=False, index=True)
    device_id = Column(String(32), nullable=False)
    timestamp = Column(DateTime, nullable=False, index=True)   # heure de Paris
    id_seance = Column(Integer, nullable=True, index=True)
    recu_le = Column(DateTime, nullable=True)                  # heure de réception serveur

class PresenceManuelleDB(Base):
    """Statut saisi à la main par le prof (boîtier en panne, oubli de carte...).
    Il remplace le statut calculé à partir des bips pour cet étudiant et ce cours."""
    __tablename__ = "presences_manuelles"
    id_seance = Column(Integer, primary_key=True)              # 1er créneau du bloc
    id_etudiant = Column(Integer, ForeignKey("etudiants.id", ondelete="CASCADE"), primary_key=True)
    statut = Column(String(16), nullable=False)                # Présent / En retard / Absent
    modifie_le = Column(DateTime, nullable=True)

class SeanceDB(Base):
    __tablename__ = "seances"
    id = Column(Integer, primary_key=True, index=True)
    uid_ical = Column(String(255), nullable=True, index=True)  # UID de l'événement iCal
    id_enseignement = Column(Integer, ForeignKey("enseignements.id"), nullable=False)
    id_groupe = Column(Integer, ForeignKey("groupes.id"), nullable=False)
    id_salle = Column(Integer, ForeignKey("salles.id"), nullable=False)
    id_prof = Column(Integer, ForeignKey("professeurs.id"), nullable=False)
    date_debut = Column(DateTime, nullable=False)
    date_fin = Column(DateTime, nullable=False)


def migrer_schema(engine):
    """create_all() crée les tables manquantes mais ne modifie pas les tables
    existantes. Cette fonction applique à la main les changements faits sur
    des tables qui existaient déjà dans PostgreSQL. Elle peut tourner à chaque
    démarrage sans risque."""
    insp = inspect(engine)
    if insp.has_table("boitiers") and "mode_sae" not in {c["name"] for c in insp.get_columns("boitiers")}:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE boitiers ADD COLUMN mode_sae BOOLEAN NOT NULL DEFAULT false"))
    if insp.has_table("boitiers") and "accueil" not in {c["name"] for c in insp.get_columns("boitiers")}:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE boitiers ADD COLUMN accueil BOOLEAN NOT NULL DEFAULT false"))
            # Boîtiers existants nommés "...ACCUEIL" / "...ACCEUIL" : cochés d'office
            conn.execute(text("UPDATE boitiers SET accueil = true "
                              "WHERE upper(device_id) LIKE '%ACCUEIL%' OR upper(device_id) LIKE '%ACCEUIL%'"))
    if insp.has_table("professeurs"):
        colonnes = {c["name"] for c in insp.get_columns("professeurs")}
        with engine.begin() as conn:
            if "identifiant" not in colonnes:
                conn.execute(text("ALTER TABLE professeurs ADD COLUMN identifiant VARCHAR(64)"))
                conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_professeurs_identifiant "
                                  "ON professeurs (identifiant)"))
            if "mot_de_passe" not in colonnes:
                conn.execute(text("ALTER TABLE professeurs ADD COLUMN mot_de_passe VARCHAR(255)"))
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        if insp.has_table("seances"):
            conn.execute(text("ALTER TABLE seances ADD COLUMN IF NOT EXISTS uid_ical VARCHAR(255)"))
        if insp.has_table("pointages"):
            conn.execute(text("ALTER TABLE pointages ADD COLUMN IF NOT EXISTS recu_le TIMESTAMP"))
            type_ts = conn.execute(text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name = 'pointages' AND column_name = 'timestamp'"
            )).scalar()
            if type_ts and type_ts.startswith("character"):
                # Ancienne version : timestamp stocké en texte -> conversion en vraie date
                conn.execute(text(
                    'ALTER TABLE pointages ALTER COLUMN "timestamp" TYPE TIMESTAMP '
                    'USING NULLIF("timestamp", \'\')::timestamp'
                ))
