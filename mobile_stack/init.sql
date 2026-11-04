ALTER USER 'root'@'localhost' IDENTIFIED BY 'Admin@123';
CREATE USER IF NOT EXISTS 'isotrax'@'localhost' IDENTIFIED BY 'IsoTrax_GW_2026!';
GRANT ALL PRIVILEGES ON *.* TO 'isotrax'@'localhost';
FLUSH PRIVILEGES;
