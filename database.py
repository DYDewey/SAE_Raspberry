import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Charge les variables du fichier .env
load_dotenv()

db_user = os.getenv("DB_USER", "postgres")
db_password = os.getenv("DB_PASSWORD")
db_name = os.getenv("DB_NAME", "postgres")

SQLALCHEMY_DATABASE_URL = f"postgresql://{db_user}:{db_password}@localhost:5432/{db_name}"

engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()