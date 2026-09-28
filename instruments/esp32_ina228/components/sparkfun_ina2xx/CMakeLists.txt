set(SPARKFUN_INA2XX_ROOT
    "${CMAKE_CURRENT_LIST_DIR}/../../lib/SparkFun_INA2XX_Arduino_Library")
set(SPARKFUN_TOOLKIT_ROOT
    "${CMAKE_CURRENT_LIST_DIR}/../../lib/SparkFun_Toolkit")

if(NOT EXISTS "${SPARKFUN_INA2XX_ROOT}/src/sfTk/sfDevINA228.cpp")
    message(FATAL_ERROR
        "SparkFun INA2XX submodule is missing. Run: git submodule update --init --recursive")
endif()

if(NOT EXISTS "${SPARKFUN_TOOLKIT_ROOT}/src/sfTk/sfToolkit.cpp")
    message(FATAL_ERROR
        "SparkFun Toolkit submodule is missing. Run: git submodule update --init --recursive")
endif()

# Only the platform-independent SparkFun sources are compiled. Arduino.h,
# Wire, sfTkArdI2C and the Arduino wrappers are deliberately excluded.
idf_component_register(
    SRCS
        "${SPARKFUN_TOOLKIT_ROOT}/src/sfTk/sfToolkit.cpp"
        "${SPARKFUN_INA2XX_ROOT}/src/sfTk/sfDevINA2XX.cpp"
        "${SPARKFUN_INA2XX_ROOT}/src/sfTk/sfDevINA228.cpp"
    INCLUDE_DIRS
        "${SPARKFUN_TOOLKIT_ROOT}/src"
        "${SPARKFUN_TOOLKIT_ROOT}/src/sfTk"
        "${SPARKFUN_INA2XX_ROOT}/src"
        "${SPARKFUN_INA2XX_ROOT}/src/sfTk"
)
