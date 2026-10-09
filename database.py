import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Charge les variables du fichier .env
load_dotenv()

db_user = os.getenv("DB_USER", "postgres")
db_password = os.getenv("DB_PASSWORD")
db_name = os.getenv("DB_NAME", "postgres")
db_host = os.getenv("DB_HOST", "localhost")
db_port = os.getenv("DB_PORT", "5432")

# "postgresql+psycopg" = driver psycopg 3 (celui du requirements.txt).
# "postgresql://" tout court chercherait psycopg2, qui n'est pas installé.
# DATABASE_URL permet de forcer une autre base (ex : sqlite:///test.db pour les tests).
SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"postgresql+psycopg://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}",
)

engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Dépendance FastAPI : une session de base de données par requête."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
