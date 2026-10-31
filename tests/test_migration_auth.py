from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from config import ROOT_DIR, settings


def test_auth_migration_preserves_legacy_teacher_and_evaluation(tmp_path):
    database_path = tmp_path / "legacy.db"
    old_url = settings.database_url
    test_url = f"sqlite:///{database_path.as_posix()}"
    settings.database_url = test_url
    config = Config(str(ROOT_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", test_url)
    try:
        command.upgrade(config, "0002_teacher_feedback")
        engine = create_engine(test_url)
        with engine.begin() as connection:
            connection.execute(text("""INSERT INTO teachers
                (id, name, institution, email, feedback_style, grading_strictness, manual_review_required, created_at)
                VALUES (1, 'Legacy Teacher', 'Old School', 'legacy@school.edu', 'Constructive and concise', 'Balanced', 1, CURRENT_TIMESTAMP)"""))
            connection.execute(text("""INSERT INTO students
                (id, teacher_id, student_code, name, class_grade, email, is_demo, created_at)
                VALUES (10, 1, 'L-1', 'Legacy Student', 'Grade 9', '', 0, CURRENT_TIMESTAMP)"""))
            connection.execute(text("""INSERT INTO examinations
                (id, teacher_id, title, subject, class_grade, academic_year, exam_date, total_marks, is_demo, created_at)
                VALUES (20, 1, 'Legacy Exam', 'Physics', 'Grade 9', '2026', '2026-10-01', 10, 0, CURRENT_TIMESTAMP)"""))
            connection.execute(text("""INSERT INTO evaluations
                (id, teacher_id, student_id, examination_id, status, is_demo, total_obtained, percent, overall_feedback, model_name, ai_confidence, evaluated_at)
                VALUES (30, 1, 10, 20, 'approved', 0, 8, 80, 'Good work', 'Legacy Model', 0.8, CURRENT_TIMESTAMP)"""))
        with engine.begin() as connection:
            # Simulate an existing create_all database which has real records but
            # was never adopted into Alembic's migration history.
            connection.execute(text("DROP TABLE alembic_version"))
        from scripts.migrate_existing import migrate
        migrate()
        with engine.connect() as connection:
            teacher = connection.execute(text("SELECT name, email, password_hash, is_legacy_owner, email_verified FROM teachers WHERE id = 1")).one()
            evaluation = connection.execute(text("SELECT id, teacher_id, student_id, examination_id, total_obtained FROM evaluations WHERE id = 30")).one()
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert teacher.name == "Legacy Teacher"
        assert teacher.email == "legacy@school.edu"
        assert teacher.password_hash is None
        assert bool(teacher.is_legacy_owner)
        assert bool(teacher.email_verified)
        assert tuple(evaluation) == (30, 1, 10, 20, 8.0)
        assert revision == "0004_auth_sessions"
        engine.dispose()
    finally:
        settings.database_url = old_url
