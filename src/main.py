from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

class Vehicle(BaseModel):
    license_plate: str
    brand: str
    model: str

@app.get("/vehicles")
async def get_vehicles():
    return [
        {"license_plate": "ABC123", "brand": "Toyota", "model": "Corolla"},
        {"license_plate": "XYZ456", "brand": "Ford", "model": "Focus"}
    ]
