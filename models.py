from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Table
from sqlalchemy.orm import relationship
from database import Base

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

class EtudiantDB(Base):
    __tablename__ = "etudiants"
    id = Column(Integer, primary_key=True, index=True)
    numero_etudiant = Column(String(32), unique=True, index=True, nullable=False)
    nom = Column(String(64), nullable=False)
    prenom = Column(String(64), nullable=False)

    groupes = relationship("GroupeDB", secondary=etudiant_groupe_association, back_populates="etudiants")
    carte = relationship("CarteDB", back_populates="etudiant", uselist=False)

class CarteDB(Base):
    __tablename__ = "cartes"
    nfc_uid = Column(String(64), primary_key=True, index=True)
    id_etudiant = Column(Integer, ForeignKey("etudiants.id"), unique=True, nullable=False)

    etudiant = relationship("EtudiantDB", back_populates="carte")

class PointageDB(Base):
    __tablename__ = "pointages"
    uuid = Column(String(36), primary_key=True, index=True)
    nfc_uid = Column(String(64), nullable=False)
    device_id = Column(String(32), nullable=False)
    timestamp = Column(String(64), nullable=False)
    id_seance = Column(Integer, nullable=True)

class SeanceDB(Base):
    __tablename__ = "seances"
    id = Column(Integer, primary_key=True, index=True)
    id_enseignement = Column(Integer, ForeignKey("enseignements.id"), nullable=False)
    id_groupe = Column(Integer, ForeignKey("groupes.id"), nullable=False)
    id_salle = Column(Integer, ForeignKey("salles.id"), nullable=False)
    id_prof = Column(Integer, ForeignKey("professeurs.id"), nullable=False)
    date_debut = Column(DateTime, nullable=False)
    date_fin = Column(DateTime, nullable=False)