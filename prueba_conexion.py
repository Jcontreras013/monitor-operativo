import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

print("1. Configurando el bot en Modo Fantasma (Nube)...")
chrome_options = Options()
chrome_options.add_argument("--headless") 
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument("--window-size=1920,1080")

driver = webdriver.Chrome(options=chrome_options)

try:
    print("2. Navegando a Cepheus...")
    driver.get("http://190.94.220.198:8080/Cepheus/Login.aspx")
    time.sleep(3) 

    print("3. Escribiendo credenciales...")
    # Usando los IDs exactos de tu sistema
    driver.find_element(By.ID, "txtusername").send_keys("jaison.conreras")
    driver.find_element(By.ID, "txtpass").send_keys("ja1son.con")
    
    print("4. Dando clic en Ingresar...")
    driver.find_element(By.XPATH, "//button[@type='submit']").click()
    
    print("5. Esperando a que cargue la pantalla principal...")
    time.sleep(5) 

    print("6. Tomando fotografía de la pantalla...")
    driver.save_screenshot("prueba_login.png")
    print("¡Éxito! Revisa tus archivos, ya debería estar 'prueba_login.png'")

finally:
    driver.quit()
    print("Prueba finalizada.")
