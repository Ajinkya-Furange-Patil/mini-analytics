def test_admin_login_success_and_logout(client):
    res = client.post("/admin/login", data={"username": "admin", "password": "admin123"}, follow_redirects=True)
    assert res.status_code == 200
    assert b"Mini Analytics" in res.data
    assert b"Sign Out" in res.data

    # Logout
    res_logout = client.post("/admin/logout", follow_redirects=True)
    assert res_logout.status_code == 200
    assert b"Sign in to access visitor statistics" in res_logout.data


def test_admin_login_invalid_credentials(client):
    res = client.post("/admin/login", data={"username": "admin", "password": "wrongpassword"})
    assert res.status_code == 401
    assert b"Invalid username or password" in res.data


def test_tracker_js_served(client):
    res = client.get("/tracker.js")
    assert res.status_code == 200
    assert "application/javascript" in res.content_type
    assert b"Mini Analytics" in res.data


def test_health_endpoint(client):
    res = client.get("/health")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "ok"
    assert data["database_connected"] is True
