import sqlite3
from fastapi import FastAPI, Depends, HTTPException,status, Query, Response, File, UploadFile, BackgroundTasks
import schema, models, database, oauth2
from database import engine,SessionLocal
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from routers import authentication, user
from pydantic import BaseModel, EmailStr
from typing import Optional, List
from fastapi.middleware.cors import CORSMiddleware
from typing import Union
from minio import Minio
from minio.error import S3Error
import minio, uuid, io
import datetime
import base64
from io import BytesIO
from fastapi import BackgroundTasks


app = FastAPI()

# Configure CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Update this with the origins that should be allowed
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

models.Base.metadata.create_all(engine)
app.include_router(authentication.router)
app.include_router(user.router)

minio_client = Minio(
    "127.0.0.1:9000",
    access_key="5rv9URqyQUpPokY9voaC",
    secret_key="3Prm4KHtfRu3JSo15S50ceyq6dIJ957RrziixTj1",
    secure=False  # Change to True if using HTTPS
)

class PostCreate(BaseModel):
    username: str
    content: str
    image: str = None

@app.on_event("startup")
async def startup():
    # Connect to the SQLite database
    app.state.conn = sqlite3.connect('blogs.db')
    app.state.conn.execute('''
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            content TEXT,
            image TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    app.state.conn.execute('''
    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        notification TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')

@app.on_event("shutdown")
async def shutdown():
    # Close the database connection on shutdown
    app.state.conn.close()

@app.post("/posts/", status_code=status.HTTP_201_CREATED)
async def create_post(post: PostCreate, background_tasks: BackgroundTasks):
    if post.image:
        try:
            image_data = base64.b64decode(post.image.split(",")[1])

            # Upload the image to MinIO
            image_name = f"{post.username}_{str(uuid.uuid4())}.jpg"  # Generate a unique image name

            minio_client.put_object("image", image_name, BytesIO(image_data), len(image_data))
            print("cholse")
            # Get the URL of the uploaded image
            image_url = f"https://127.0.0.1:9000/image/{image_name}"
            values = (post.username, post.content, image_url)
        except Exception as e:
            print(f"An error occurred: {e}")    

    query = '''
        INSERT INTO posts (username, content, image)
        VALUES (?, ?, ?)
    '''
    values = (post.username, post.content, post.image)  # Initialize with an empty URL

    c = app.state.conn.cursor()
    c.execute(query, values)
    app.state.conn.commit()

    notification = f"{post.username} posted a new post"
    c.execute("INSERT INTO notifications (username, notification) VALUES (?, ?)", (post.username, notification))
    app.state.conn.commit() 

    background_tasks.add_task(clear_old_notifications)

def clear_old_notifications():
    try:
        cutoff_time = datetime.datetime.now() - datetime.timedelta(minutes=5)
        c = app.state.conn.cursor()
        c.execute("DELETE FROM notifications WHERE created_at <= ?", (cutoff_time,))
        app.state.conn.commit()
        print("Cleared old notifications")
    except Exception as e:
        print(f"An error occurred while clearing notifications: {e}")

    return {"message": "Post created successfully"}


@app.get("/posts/")
async def get_posts():
    query = "SELECT username, content, image, created_at FROM posts ORDER BY created_at DESC"  # Order by creation timestamp in descending order
    c = app.state.conn.cursor()
    c.execute(query)
    rows = c.fetchall()
    posts = [{"username": row[0], "content": row[1], "image": row[2], "created_at": row[3]} for row in rows]
    return {"posts": posts}


@app.get("/notifications/")
async def get_notifications():
    query = "SELECT notification, created_at, username FROM notifications"  # Include the username in the query
    c = app.state.conn.cursor()
    c.execute(query)
    rows = c.fetchall()
    notifications = [{"notification": row[0], "created_at": row[1], "username": row[2]} for row in rows]
    return {"notifications": notifications}



@app.get("/posts/{post_id}")
async def get_post(post_id: int):
    query = "SELECT username, content, image FROM posts WHERE id = ?"
    c = app.state.conn.cursor()
    c.execute(query, (post_id,))
    row = c.fetchone()

    if row:
        username, content, image = row
        post = {"username": username, "content": content, "image": image}
        return {"post": post}
    else:
        return {"error": "Post not found"}
