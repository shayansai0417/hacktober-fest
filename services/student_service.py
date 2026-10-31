"""Student workspace CRUD with owner checks at the service boundary."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import Student


def _owned_student(session: Session, student_id: int, teacher_id: int) -> Student:
    student = session.scalar(select(Student).where(Student.id == student_id, Student.teacher_id == teacher_id))
    if student is None:
        raise PermissionError("Student record not found in this teacher workspace.")
    return student


def create_student(session: Session, *, teacher_id: int, name: str, student_code: str = "", class_grade: str, email: str = "", is_demo: bool = False) -> Student:
    clean_name, clean_class, clean_code = name.strip(), class_grade.strip(), student_code.strip()
    if not clean_name or not clean_class:
        raise ValueError("Student name and class are required.")
    if clean_code and session.scalar(select(Student.id).where(Student.teacher_id == teacher_id, Student.student_code == clean_code)):
        raise ValueError("That student ID already exists in this teacher workspace.")
    student = Student(teacher_id=teacher_id, name=clean_name, student_code=clean_code or None, class_grade=clean_class, email=email.strip(), is_demo=is_demo)
    session.add(student)
    session.flush()
    return student


def update_student(session: Session, student_id: int, *, teacher_id: int, name: str, student_code: str, class_grade: str, email: str) -> Student:
    student = _owned_student(session, student_id, teacher_id)
    clean_name, clean_class, clean_code = name.strip(), class_grade.strip(), student_code.strip()
    if not clean_name or not clean_class:
        raise ValueError("Student name and class are required.")
    if clean_code and session.scalar(select(Student.id).where(Student.teacher_id == teacher_id, Student.student_code == clean_code, Student.id != student.id)):
        raise ValueError("That student ID is already in use in this teacher workspace.")
    student.name, student.student_code, student.class_grade, student.email = clean_name, clean_code or None, clean_class, email.strip()
    return student


def delete_student(session: Session, student_id: int, *, teacher_id: int) -> None:
    student = _owned_student(session, student_id, teacher_id)
    if student.evaluations:
        raise ValueError("A student with saved evaluations cannot be deleted.")
    session.delete(student)
