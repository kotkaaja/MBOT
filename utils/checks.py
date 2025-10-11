import time
from typing import Tuple

# Dictionary untuk menyimpan timestamp terakhir kali pengguna menggunakan perintah
user_cooldowns = {}

def check_user_cooldown(user_id: int, command: str, cooldown_seconds: int) -> Tuple[bool, int]:
    """
    Memeriksa cooldown untuk seorang pengguna pada perintah tertentu.

    Args:
        user_id (int): ID pengguna Discord.
        command (str): Nama perintah yang digunakan.
        cooldown_seconds (int): Durasi cooldown dalam detik.

    Returns:
        Tuple[bool, int]: 
            - bool: True jika pengguna bisa melanjutkan, False jika masih dalam cooldown.
            - int: Sisa waktu cooldown dalam detik (0 jika bisa melanjutkan).
    """
    current_time = time.time()
    cooldown_key = f"{user_id}_{command}"

    if cooldown_key in user_cooldowns:
        # Menghitung sisa waktu cooldown
        time_left = cooldown_seconds - (current_time - user_cooldowns[cooldown_key])
        if time_left > 0:
            return False, int(time_left)  # Masih dalam cooldown

    # Jika tidak dalam cooldown, perbarui timestamp dan izinkan perintah
    user_cooldowns[cooldown_key] = current_time
    return True, 0

