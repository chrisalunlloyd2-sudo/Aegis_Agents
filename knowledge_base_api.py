#!/usr/bin/env python3
"""
Algorithm & Code Knowledge Base API
Extends gemini_bridge_api.py with TimescaleDB integration
Tracks what worked, what didn't, and why

Access this via web UI after TimescaleDB setup
"""

from flask import Flask, request, jsonify
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
import os

# TimescaleDB Connection
def get_db_connection():
    """Connect to TimescaleDB knowledge base"""
    conn = psycopg2.connect(
        host=os.getenv('TIMESCALE_HOST', 'localhost'),
        database=os.getenv('TIMESCALE_DB', 'algorithm_kb'),
        user=os.getenv('TIMESCALE_USER', 'postgres'),
        password=os.getenv('TIMESCALE_PASSWORD', 'password')
    )
    return conn

class AlgorithmKnowledgeBase:
    """Shared knowledge database for code and algorithms"""

    @staticmethod
    def log_code_attempt(algorithm_name, language, code, status, notes):
        """Log when we try a new algorithm"""
        conn = get_db_connection()
        cur = conn.cursor()

        try:
            cur.execute("""
                INSERT INTO code_attempts
                (algorithm_name, language, code_snippet, status, failure_reason, context)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (algorithm_name, language, code, status, notes, 'gemini_bridge'))

            attempt_id = cur.fetchone()[0]
            conn.commit()
            return attempt_id
        finally:
            cur.close()
            conn.close()

    @staticmethod
    def log_lesson_learned(problem, attempted_solution, result, insight):
        """Log lessons we discover"""
        conn = get_db_connection()
        cur = conn.cursor()

        try:
            cur.execute("""
                INSERT INTO lessons_learned
                (problem_statement, attempted_solution, result, key_insight)
                VALUES (%s, %s, %s, %s)
                RETURNING id
            """, (problem, attempted_solution, result, insight))

            lesson_id = cur.fetchone()[0]
            conn.commit()
            return lesson_id
        finally:
            cur.close()
            conn.close()

    @staticmethod
    def add_working_pattern(name, description, use_cases, effectiveness):
        """Add a pattern that works well"""
        conn = get_db_connection()
        cur = conn.cursor()

        try:
            cur.execute("""
                INSERT INTO working_patterns
                (pattern_name, description, use_cases, effectiveness_score)
                VALUES (%s, %s, %s, %s)
                RETURNING id
            """, (name, description, use_cases, effectiveness))

            pattern_id = cur.fetchone()[0]
            conn.commit()
            return pattern_id
        finally:
            cur.close()
            conn.close()

    @staticmethod
    def get_effectiveness_dashboard():
        """Get dashboard view of what works best"""
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            cur.execute("SELECT * FROM algorithm_effectiveness_summary")
            return cur.fetchall()
        finally:
            cur.close()
            conn.close()

    @staticmethod
    def get_failed_approaches():
        """Learn what NOT to do"""
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            cur.execute("""
                SELECT * FROM failed_approaches
                ORDER BY attempted_at DESC
                LIMIT 50
            """)
            return cur.fetchall()
        finally:
            cur.close()
            conn.close()

    @staticmethod
    def search_similar_problems(problem_description):
        """Find similar problems we've solved before"""
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            # Simple substring search (upgrade to vector search with pgvector)
            cur.execute("""
                SELECT * FROM lessons_learned
                WHERE problem_statement ILIKE %s
                ORDER BY learned_at DESC
                LIMIT 10
            """, (f'%{problem_description}%',))
            return cur.fetchall()
        finally:
            cur.close()
            conn.close()

# API Routes (Add to Flask app)
def register_kb_routes(app):
    """Register knowledge base routes"""

    @app.route('/api/kb/log-attempt', methods=['POST'])
    def log_attempt():
        """Log a code attempt"""
        data = request.json
        try:
            attempt_id = AlgorithmKnowledgeBase.log_code_attempt(
                data.get('algorithm_name'),
                data.get('language'),
                data.get('code'),
                data.get('status'),  # 'working', 'failed', 'partial'
                data.get('notes')
            )
            return jsonify({
                'status': 'logged',
                'attempt_id': attempt_id
            }), 201
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/kb/effectiveness', methods=['GET'])
    def get_effectiveness():
        """Get effectiveness dashboard"""
        try:
            data = AlgorithmKnowledgeBase.get_effectiveness_dashboard()
            return jsonify(data), 200
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/kb/failed-approaches', methods=['GET'])
    def get_failed():
        """Get failed approaches to avoid"""
        try:
            data = AlgorithmKnowledgeBase.get_failed_approaches()
            return jsonify(data), 200
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/kb/lessons', methods=['POST'])
    def add_lesson():
        """Log a lesson learned"""
        data = request.json
        try:
            lesson_id = AlgorithmKnowledgeBase.log_lesson_learned(
                data.get('problem'),
                data.get('attempted_solution'),
                data.get('result'),
                data.get('insight')
            )
            return jsonify({
                'status': 'logged',
                'lesson_id': lesson_id
            }), 201
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/kb/search', methods=['GET'])
    def search_kb():
        """Search knowledge base for similar problems"""
        query = request.args.get('q')
        try:
            results = AlgorithmKnowledgeBase.search_similar_problems(query)
            return jsonify(results), 200
        except Exception as e:
            return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    print("Knowledge Base API ready to integrate with gemini_bridge_api.py")
