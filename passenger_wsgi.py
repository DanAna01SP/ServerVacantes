# Punto de entrada para cPanel ("Setup Python App" / Phusion Passenger).
# cPanel busca la variable "application" en este archivo.
from app import app as application  # noqa: F401
