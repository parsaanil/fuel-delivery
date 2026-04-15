# FuelAid — Enhanced Edition

Emergency fuel delivery & roadside assistance platform built with Flask + Socket.IO.

## New Features Added

### 1. ✅ Customer Delivery Confirmation
When a fuel agent or mechanic marks a job as "done", the status changes to **Awaiting Confirmation** and the customer receives a real-time notification. The customer must click **"Confirm Receipt"** before the job is fully closed. This two-step confirmation protects both parties.

### 2. ⭐ Customer Feedback for Delivery Agent
After confirming delivery, customers can rate the agent (1–5 stars) and leave a comment. Ratings appear on:
- The customer's request history
- The agent's/mechanic's delivery history table
- The admin's feedback panel

### 3. ⛽ Live Fuel Price Display
Current Hyderabad fuel prices (Petrol, Diesel, CNG) are shown prominently on:
- The **main landing page** (index) — visible to all visitors before login
- The **customer dashboard** — in a price ticker at the top
- The **fuel agent dashboard** — as a quick reference strip
- The **admin dashboard** — with update instructions

To update prices, edit `FUEL_PRICES` dict in `app.py`:
```python
FUEL_PRICES = {'petrol': 102.63, 'diesel': 88.74, 'cng': 76.00}
```

### 4. 💰 Cost Quotation
Before submitting a request, customers see a real-time cost breakdown:
- **Fuel requests**: Fuel cost (price × litres) + Delivery charge (₹30 + ₹8/km)
- **Roadside/Maintenance**: Service call (₹250) + Travel charge (₹8/km)
- Quote updates live as the user changes fuel type, liters, or service type

### 5. 🕐 Estimated Delivery Time
ETA is calculated based on distance from provider to customer at 35 km/h average speed + 5 min buffer. Displayed:
- In the quotation box before submitting
- In the confirmation toast after submitting
- In the requests table (for ongoing requests)
- On the agent's active delivery card

### 6. 📂 Separate CSV Storage
User data is automatically saved to three CSV files:
| File | Contents |
|------|----------|
| `customers.csv` | id, name, email, phone, vehicle, lat, lon, joined |
| `agents.csv` | id, name, email, phone, lat, lon, verified, joined, total_deliveries |
| `mechanics.csv` | id, name, email, phone, lat, lon, verified, joined, total_jobs |

Records are created on registration, updated on verification, and job counts sync after each completion. Admins can download all three CSVs from the admin dashboard.

## Setup

```bash
pip install flask flask-socketio
python app.py
```

### Author
Anil parsa
