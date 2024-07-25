from flask import Flask, render_template, request, redirect, url_for, jsonify, session
import mysql.connector
from mysql.connector import Error
from werkzeug.utils import secure_filename
import os
import logging
import uuid

app = Flask(__name__)
app.secret_key = os.urandom(24)

UPLOAD_FOLDER = 'static/uploads/'
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

logging.basicConfig(level=logging.DEBUG)

db_config = {
    'user': 'root',
    'password': '',
    'host': 'localhost',
    'database': 'codtech_db'
}

def get_db_connection():
    try:
        connection = mysql.connector.connect(**db_config)
        if connection.is_connected():
            return connection
    except Error as e:
        logging.error(f"Error connecting to MySQL: {e}")
    return None

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    username = session.get('username')
    user_id = None
    if username:
        cursor.execute('SELECT id FROM users WHERE username = %s', (username,))
        user = cursor.fetchone()
        if user:
            user_id = user['id']
        else:
            logging.error(f"User with username {username} not found")
            return redirect(url_for('login'))

    cursor.execute('''
        SELECT u.id, u.name, u.interest, u.img
        FROM users u
        LEFT JOIN user_friends uf ON u.id = uf.friend_id AND uf.user_id = %s
        WHERE u.id != %s AND uf.friend_id IS NULL
        LIMIT 5
    ''', (user_id, user_id))
    initial_friends = cursor.fetchall()

    cursor.execute('SELECT * FROM news_feed')
    news_feed = cursor.fetchall()

    cursor.close()
    connection.close()
    return render_template('index.html', initial_friends=initial_friends, news_feed=news_feed, no_recommendations=len(initial_friends) == 0)

@app.route('/load_more_friends', methods=['POST'])
def load_more_friends():
    last_friend_id = request.json.get('last_friend_id', 0)
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    cursor.execute('SELECT id, name, interest, img FROM users WHERE id > %s LIMIT 5', (last_friend_id,))
    new_friends = cursor.fetchall()

    cursor.close()
    connection.close()
    return jsonify(new_friends)

@app.route('/news_feed_updates', methods=['GET'])
def news_feed_updates():
    if 'username' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    username = session['username']
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    cursor.execute('SELECT id FROM users WHERE username = %s', (username,))
    user = cursor.fetchone()
    user_id = user['id']

    cursor.execute('''
        SELECT nf.message, nf.created_at, u.name AS sender_name
        FROM news_feed nf
        LEFT JOIN users u ON nf.sender_id = u.id
        WHERE nf.user_id = %s
        ORDER BY nf.created_at DESC
    ''', (user_id,))
    news_feed = cursor.fetchall()

    cursor.close()
    connection.close()
    return jsonify(news_feed)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute('SELECT * FROM users WHERE username = %s AND password = %s', (username, password))
        user = cursor.fetchone()

        cursor.close()
        connection.close()

        if user:
            session['username'] = username
            return redirect(url_for('index'))
        return "Invalid credentials", 401
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        interest = request.form['interest']
        name = request.form['name']

        file = request.files.get('img')
        img_path = None
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            img_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(img_path)

        user_id = str(uuid.uuid4()) 
        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute('''
            INSERT INTO users (id, username, password, interest, name, img)
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', (user_id, username, password, interest, name, filename))
        connection.commit()

        cursor.close()
        connection.close()
        return redirect(url_for('login'))
    return render_template('signup.html')

@app.route('/find_friends', methods=['POST'])
def find_friends():
    user_interest = request.json.get('interest')
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    cursor.execute('SELECT id, name, interest, img FROM users WHERE interest = %s', (user_interest,))
    matched_friends = cursor.fetchall()

    cursor.close()
    connection.close()
    return jsonify(matched_friends)

@app.route('/profile')
def profile():
    if 'username' not in session:
        return redirect(url_for('login'))
    username = session['username']
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    cursor.execute('SELECT * FROM users WHERE username = %s', (username,))
    user_details = cursor.fetchone()

    cursor.close()
    connection.close()
    return render_template('profile.html', user=user_details)

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))

@app.route('/add_friend', methods=['POST'])
def add_friend():
    data = request.json
    friend_id = data.get('friend_id')
    username = session.get('username')

    if not username:
        return jsonify({'error': 'Not logged in'}), 401

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute('SELECT id FROM users WHERE username = %s', (username,))
        user = cursor.fetchone()
        if not user:
            logging.error("User not found")
            return jsonify({'error': 'User not found'}), 404

        user_id = user['id']

        cursor.execute('SELECT id FROM users WHERE id = %s', (friend_id,))
        if not cursor.fetchone():
            logging.error("Friend does not exist")
            return jsonify({'error': 'Friend does not exist'}), 404

        cursor.execute('SELECT * FROM user_friends WHERE user_id = %s AND friend_id = %s', (user_id, friend_id))
        if cursor.fetchone():
            logging.error("Already friends")
            return jsonify({'error': 'Already friends'}), 400

        cursor.execute('INSERT INTO user_friends (user_id, friend_id) VALUES (%s, %s)', (user_id, friend_id))
        connection.commit()

        message = f'You added user with ID {friend_id} as a friend.'
        cursor.execute('INSERT INTO news_feed (message, user_id) VALUES (%s, %s)', (message, user_id))
        connection.commit()

    except Error as e:
        logging.error(f"Error: {e}")
        connection.rollback()
        return jsonify({'error': 'Failed to add friend'}), 500
    finally:
        cursor.close()
        connection.close()

    return jsonify({'success': True})

@app.route('/send_friend_request', methods=['POST'])
def send_friend_request():
    data = request.json
    friend_id = data.get('friend_id')
    username = session.get('username')

    if not username:
        return jsonify({'error': 'Not logged in'}), 401

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute('SELECT id FROM users WHERE username = %s', (username,))
        user = cursor.fetchone()
        if not user:
            return jsonify({'error': 'User not found'}), 404

        user_id = user['id']

        cursor.execute('SELECT id FROM users WHERE id = %s', (friend_id,))
        if not cursor.fetchone():
            return jsonify({'error': 'Friend does not exist'}), 404

        cursor.execute('SELECT * FROM friend_requests WHERE sender_id = %s AND receiver_id = %s', (user_id, friend_id))
        if cursor.fetchone():
            return jsonify({'error': 'Request already sent'}), 400

        cursor.execute('INSERT INTO friend_requests (sender_id, receiver_id, status) VALUES (%s, %s, %s)', (user_id, friend_id, 'pending'))
        connection.commit()

        cursor.execute('INSERT INTO news_feed (message) VALUES (%s)', (f'{username} sent you a friend request.',))
        connection.commit()

    except Error as e:
        logging.error(f"Error: {e}")
        connection.rollback()
        return jsonify({'error': 'Failed to send friend request'}), 500
    finally:
        cursor.close()
        connection.close()

    return jsonify({'success': True})

@app.route('/accept_friend_request', methods=['POST'])
def accept_friend_request():
    data = request.json
    request_id = data.get('request_id')
    username = session.get('username')

    if not username:
        return jsonify({'error': 'Not logged in'}), 401

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute('SELECT id FROM users WHERE username = %s', (username,))
        user = cursor.fetchone()
        user_id = user['id']

        cursor.execute('SELECT * FROM friend_requests WHERE id = %s AND receiver_id = %s AND status = "pending"', (request_id, user_id))
        request_details = cursor.fetchone()

        if not request_details:
            return jsonify({'error': 'Friend request not found or already processed'}), 404

        cursor.execute('UPDATE friend_requests SET status = "accepted" WHERE id = %s', (request_id,))
        connection.commit()

        cursor.execute('INSERT INTO user_friends (user_id, friend_id) VALUES (%s, %s)', (user_id, request_details['sender_id']))
        cursor.execute('INSERT INTO user_friends (user_id, friend_id) VALUES (%s, %s)', (request_details['sender_id'], user_id))
        connection.commit()

        cursor.execute('INSERT INTO news_feed (message) VALUES (%s)', (f'{username} accepted your friend request.',))
        connection.commit()

    except Error as e:
        logging.error(f"Error: {e}")
        connection.rollback()
        return jsonify({'error': 'Failed to accept friend request'}), 500
    finally:
        cursor.close()
        connection.close()

    return jsonify({'success': True})

@app.route('/friend_requests')
def friend_requests():
    if 'username' not in session:
        return redirect(url_for('login'))
    username = session['username']
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    cursor.execute('SELECT id FROM users WHERE username = %s', (username,))
    user = cursor.fetchone()
    user_id = user['id']

    cursor.execute('''
        SELECT r.id, u.name, u.interest, u.img
        FROM friend_requests r
        JOIN users u ON r.sender_id = u.id
        WHERE r.receiver_id = %s AND r.status = 'pending'
    ''', (user_id,))
    requests = cursor.fetchall()

    cursor.close()
    connection.close()
    return render_template('friend_requests.html', requests=requests)

@app.route('/friends')
def friends_list():
    if 'username' not in session:
        return redirect(url_for('login'))
    username = session['username']
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    cursor.execute("""
        SELECT f.id, f.name, f.interest, f.img
        FROM user_friends uf 
        JOIN users f ON uf.friend_id = f.id 
        JOIN users u ON uf.user_id = u.id 
        WHERE u.username = %s
    """, (username,))
    added_friends = cursor.fetchall()

    cursor.close()
    connection.close()
    return render_template('friends.html', friends=added_friends)

@app.route('/notifications')
def notifications():
    username = session.get('username')
    if not username:
        return redirect(url_for('login'))

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    cursor.execute('SELECT id FROM users WHERE username = %s', (username,))
    user = cursor.fetchone()
    user_id = user['id']

    cursor.execute('SELECT * FROM notifications WHERE user_id = %s ORDER BY created_at DESC', (user_id,))
    notifications = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template('notifications.html', notifications=notifications)

@app.route('/messages/<int:receiver_id>', methods=['GET'])
def get_messages(receiver_id):
    if 'username' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    username = session['username']
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    cursor.execute('SELECT id FROM users WHERE username = %s', (username,))
    sender = cursor.fetchone()
    if not sender:
        return jsonify({'error': 'User not found'}), 404
    sender_id = sender['id']

    cursor.execute('''
        SELECT m.message_content, m.created_at, u.name AS sender_name , m.media_path
        FROM messages m
        JOIN users u ON m.sender_id = u.id
        WHERE (m.sender_id = %s AND m.receiver_id = %s) OR (m.sender_id = %s AND m.receiver_id = %s)
        ORDER BY m.created_at ASC
    ''', (sender_id, receiver_id, receiver_id, sender_id))
    messages = cursor.fetchall()

    cursor.close()
    connection.close()
    return jsonify(messages)

@app.route('/message/<int:receiver_id>', methods=['POST'])
def send_message(receiver_id):
    if 'username' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    username = session['username']
    message_content = request.form['message']
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute('SELECT id FROM users WHERE username = %s', (username,))
        sender = cursor.fetchone()
        if not sender:
            return jsonify({'error': 'User not found'}), 404
        sender_id = sender['id']

        file = request.files.get('file')
        media_path = None
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            media_path = os.path.join(app.config['UPLOAD_FOLDER'], 'messages', filename)
            file.save(media_path)

        cursor.execute('INSERT INTO messages (sender_id, receiver_id, message_content, media_path) VALUES (%s, %s, %s, %s)',
                       (sender_id, receiver_id, message_content, media_path))
        connection.commit()

        cursor.execute('INSERT INTO news_feed (message, user_id, sender_id) VALUES (%s, %s, %s)',
                       (f'You received a message from {username}', receiver_id, sender_id))
        connection.commit()

    except Error as e:
        logging.error(f"Error: {e}")
        return jsonify({'error': 'Failed to send message'}), 500
    finally:
        cursor.close()
        connection.close()

    return jsonify({'success': 'Message sent'})

@app.route('/change-password', methods=['POST'])
def change_password():
    if 'username' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    username = session['username']
    current_password = request.form['currentPassword']
    new_password = request.form['newPassword']

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute('SELECT * FROM users WHERE username = %s', (username,))
        user = cursor.fetchone()

        if not user:
            return jsonify({'error': 'User not found'}), 404

        if user['password'] != current_password:
            return jsonify({'error': 'Current password incorrect'}), 400

        cursor.execute('UPDATE users SET password = %s WHERE username = %s', (new_password, username))
        connection.commit()

    except Error as e:
        logging.error(f"Error: {e}")
        connection.rollback()
        return jsonify({'error': 'Failed to change password'}), 500
    finally:
        cursor.close()
        connection.close()

    return jsonify({'success': 'Password changed successfully'})

if __name__ == '__main__':
    app.run(debug=True)
